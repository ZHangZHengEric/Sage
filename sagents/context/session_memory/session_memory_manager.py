"""
历史消息检索模块

负责使用 BM25 算法对历史消息进行检索和召回
"""
import re
from typing import List

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.context_budget import ContextBudgetManager
from sagents.utils.logger import logger

from rank_bm25 import BM25Okapi


class SessionMemoryManager:
    """历史消息检索器"""
    
    def __init__(self):
        pass
    
    def _tokenize_text(self, text: str) -> List[str]:
        """文本分词（用于BM25，私有辅助方法）"""
        if not text or not text.strip():
            return []
        
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text.lower())
        tokens = []
        
        for word in text.split():
            if not word.strip():
                continue
            
            if re.search(r'[\u4e00-\u9fff]', word):
                # 中文字符和英文单词分开
                tokens.extend(re.findall(r'[\u4e00-\u9fff]', word))
                tokens.extend(re.findall(r'[a-zA-Z]+', word))
            elif len(word) > 1:
                tokens.append(word)
        
        return [t for t in tokens if t.strip()]
    
    def _calculate_message_tokens(self, msg: MessageChunk) -> int:
        """计算单条消息的token数（私有辅助方法）"""
        content = msg.get_content()
        return ContextBudgetManager.calculate_str_token_length(content)
    
    def _calculate_messages_tokens(self, messages: List[MessageChunk]) -> int:
        """计算多条消息的总token数（私有辅助方法）"""
        return sum(self._calculate_message_tokens(msg) for msg in messages)

    def _group_messages_by_chat(self, messages: List[MessageChunk]) -> List[List[MessageChunk]]:
        """按对话轮次分组消息"""
        if not messages:
            return []
            
        chats: List[List[MessageChunk]] = []
        current_chat: List[MessageChunk] = []
        
        for msg in messages:
            current_chat.append(msg)
            # 如果是assistant的消息，或者最后一条消息，结束当前轮次
            # 这里简化逻辑：只要遇到assistant消息就结束一轮，或者遇到tool calls
            # 实际上对话轮次通常是 user -> assistant
            if msg.role == 'assistant':
                chats.append(current_chat)
                current_chat = []
                
        if current_chat:
            chats.append(current_chat)
            
        return chats

    def retrieve_group_messages_by_chat(
        self,
        messages: List[MessageChunk],
        query: str,
        history_budget: int
    ) -> List[MessageChunk]:
        """使用BM25对消息重排序并限制在预算内（按对话轮次）"""
        if not messages or not query:
            return messages
         
        try:
            # 按对话轮次分组
            chat_list = self._group_messages_by_chat(messages)
             
            if not chat_list:
                return messages
             
            # 构建BM25语料库（每轮对话作为一个文档）
            corpus = []
            for chat in chat_list:
                # 合并一轮对话中所有消息的内容
                combined_content = ""
                for msg in chat:
                    content = msg.get_content()
                    combined_content += f" {content}"
                corpus.append(self._tokenize_text(combined_content.strip()))
             
            if not corpus:
                return messages
             
            # BM25重排序
            bm25 = BM25Okapi(corpus)
            query_tokens = self._tokenize_text(query)
            scores = bm25.get_scores(query_tokens)
             
            # 排序并过滤（分数>0.1）
            scored_chats = sorted(
                zip(chat_list, scores),
                key=lambda x: x[1],
                reverse=True
            )
             
            filtered = [(chat, score) for chat, score in scored_chats if score > 0.1]
            if not filtered:
                filtered = scored_chats
             
            # 按预算限制（按轮次召回）
            result = []
            total_tokens = 0
            selected_chats = 0
             
            for chat, score in filtered:
                chat_tokens = self._calculate_messages_tokens(chat)
                if total_tokens + chat_tokens <= history_budget:
                    result.extend(chat)  # 召回整轮对话
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
        history_budget: int
    ) -> List[MessageChunk]:
        """使用BM25对消息重排序并限制在预算内"""
        if not messages or not query:
            return messages
        
        try:
            # 构建BM25语料库
            corpus = []
            for msg in messages:
                content = msg.get_content()
                corpus.append(self._tokenize_text(content))
            
            if not corpus:
                return messages
            
            # BM25重排序
            bm25 = BM25Okapi(corpus)
            query_tokens = self._tokenize_text(query)
            scores = bm25.get_scores(query_tokens)
            
            # 排序并过滤（分数>0.1）
            scored_messages = sorted(
                zip(messages, scores),
                key=lambda x: x[1],
                reverse=True
            )
            
            filtered = [(msg, score) for msg, score in scored_messages if score > 0.1]
            if not filtered:
                filtered = scored_messages
            
            # 按预算限制
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

