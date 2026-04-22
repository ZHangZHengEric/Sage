"""
BM25-backed session history retrieval backend.
"""
import hashlib
import json
import re
from typing import List, Optional, Tuple

from rank_bm25 import BM25Okapi

from sagents.context.messages.context_budget import ContextBudgetManager
from sagents.context.messages.message import MessageChunk
from sagents.utils.logger import logger


class Bm25SessionMemoryBackend:
    """Default BM25 implementation for session-history retrieval."""

    def __init__(self):
        self._message_bm25_cache_key: Optional[str] = None
        self._message_bm25_cache: Optional[Tuple[BM25Okapi, List[List[str]]]] = None
        self._chat_bm25_cache_key: Optional[str] = None
        self._chat_bm25_cache: Optional[Tuple[BM25Okapi, List[List[str]], List[List[MessageChunk]]]] = None

    def clear_cache(self) -> None:
        self._message_bm25_cache_key = None
        self._message_bm25_cache = None
        self._chat_bm25_cache_key = None
        self._chat_bm25_cache = None

    def _tokenize_text(self, text: str) -> List[str]:
        if not text or not text.strip():
            return []

        text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower())
        tokens = []

        for word in text.split():
            if not word.strip():
                continue

            if re.search(r"[\u4e00-\u9fff]", word):
                tokens.extend(re.findall(r"[\u4e00-\u9fff]", word))
                tokens.extend(re.findall(r"[a-zA-Z]+", word))
            elif len(word) > 1:
                tokens.append(word)

        return [t for t in tokens if t.strip()]

    @staticmethod
    def _serialize_content(content) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)

    def _fingerprint_messages(self, messages: List[MessageChunk]) -> str:
        digests: List[str] = []
        for msg in messages:
            content = self._serialize_content(msg.get_content())
            content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            normalized_type = msg.normalized_message_type() if hasattr(msg, "normalized_message_type") else None
            digests.append(
                f"{msg.message_id}|{msg.role}|{normalized_type or ''}|{content_hash}"
            )
        return hashlib.md5("\n".join(digests).encode("utf-8")).hexdigest()

    def _calculate_message_tokens(self, msg: MessageChunk) -> int:
        return ContextBudgetManager.calculate_str_token_length(msg.get_content())

    def _calculate_messages_tokens(self, messages: List[MessageChunk]) -> int:
        return sum(self._calculate_message_tokens(msg) for msg in messages)

    def _group_messages_by_chat(self, messages: List[MessageChunk]) -> List[List[MessageChunk]]:
        if not messages:
            return []

        chats: List[List[MessageChunk]] = []
        current_chat: List[MessageChunk] = []

        for msg in messages:
            current_chat.append(msg)
            if msg.role == "assistant":
                chats.append(current_chat)
                current_chat = []

        if current_chat:
            chats.append(current_chat)

        return chats

    def _get_or_build_message_bm25(self, messages: List[MessageChunk]) -> Optional[BM25Okapi]:
        cache_key = self._fingerprint_messages(messages)
        if self._message_bm25_cache_key == cache_key and self._message_bm25_cache:
            return self._message_bm25_cache[0]

        corpus = [self._tokenize_text(msg.get_content()) for msg in messages]
        if not corpus:
            return None

        bm25 = BM25Okapi(corpus)
        self._message_bm25_cache_key = cache_key
        self._message_bm25_cache = (bm25, corpus)
        return bm25

    def _get_or_build_chat_bm25(
        self, messages: List[MessageChunk]
    ) -> Tuple[Optional[BM25Okapi], List[List[MessageChunk]]]:
        cache_key = self._fingerprint_messages(messages)
        if self._chat_bm25_cache_key == cache_key and self._chat_bm25_cache:
            return self._chat_bm25_cache[0], self._chat_bm25_cache[2]

        chat_list = self._group_messages_by_chat(messages)
        if not chat_list:
            return None, []

        corpus = []
        for chat in chat_list:
            combined_content = ""
            for msg in chat:
                combined_content += f" {msg.get_content()}"
            corpus.append(self._tokenize_text(combined_content.strip()))

        if not corpus:
            return None, chat_list

        bm25 = BM25Okapi(corpus)
        self._chat_bm25_cache_key = cache_key
        self._chat_bm25_cache = (bm25, corpus, chat_list)
        return bm25, chat_list

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        if not messages or not query:
            return messages

        try:
            bm25, chat_list = self._get_or_build_chat_bm25(messages)
            if not bm25 or not chat_list:
                return messages

            query_tokens = self._tokenize_text(query)
            scores = bm25.get_scores(query_tokens)

            scored_chats = sorted(zip(chat_list, scores), key=lambda x: x[1], reverse=True)
            filtered = [(chat, score) for chat, score in scored_chats if score > 0.1]
            if not filtered:
                filtered = scored_chats

            result = []
            total_tokens = 0
            selected_chats = 0

            for chat, score in filtered:
                chat_tokens = self._calculate_messages_tokens(chat)
                if total_tokens + chat_tokens <= history_budget:
                    result.extend(chat)
                    total_tokens += chat_tokens
                    selected_chats += 1
                else:
                    break

            logger.info(
                f"ContextBudgetManager: BM25重排序 - {len(chat_list)}轮 -> {selected_chats}轮, "
                f"{len(messages)}条 -> {len(result)}条, "
                f"使用{total_tokens}/{history_budget}tokens"
            )
            return result

        except Exception as e:
            logger.error(f"ContextBudgetManager: BM25重排序失败: {e}")
            return messages

    def retrieve_history_messages(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int,
    ) -> List[MessageChunk]:
        if not messages or not query:
            return messages

        try:
            bm25 = self._get_or_build_message_bm25(messages)
            if not bm25:
                return messages

            query_tokens = self._tokenize_text(query)
            scores = bm25.get_scores(query_tokens)

            scored_messages = sorted(zip(messages, scores), key=lambda x: x[1], reverse=True)
            filtered = [(msg, score) for msg, score in scored_messages if score > 0.1]
            if not filtered:
                filtered = scored_messages

            result = []
            total_tokens = 0
            for msg, score in filtered:
                msg_tokens = self._calculate_message_tokens(msg)
                if total_tokens + msg_tokens <= history_budget:
                    result.append(msg)
                    total_tokens += msg_tokens
                else:
                    break

            logger.info(f"HistoryMessageRetriever: 当前查询query: {query}")
            logger.info(
                f"HistoryMessageRetriever: 历史消息召回 - {len(messages)}条 -> {len(result)}条, "
                f"使用{total_tokens}/{history_budget}tokens"
            )
            return result

        except Exception as e:
            logger.error(f"HistoryMessageRetriever: 历史消息召回失败: {e}")
            return messages
