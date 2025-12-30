from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class DocumentSplit:
    def __init__(self):
        pass

    def generate_id_based_string(self, text: str, hash_fun: str = "md5") -> str:
        if hash_fun == "md5":
            return hashlib.md5(text.encode()).hexdigest()
        elif hash_fun == "sha_256":
            return hashlib.sha256(text.encode()).hexdigest()
        raise ValueError("hash_fun must be 'md5' or 'sha_256'")

    def segment_length_by_punctuation(self, text_: str, length_: int) -> List[Dict[str, Any]]:
        pattern = re.compile(r"[.。]\n?")
        positions = list(pattern.finditer(text_))
        inner_sentences = []
        start = 0
        for pos in positions:
            end = pos.end()
            if end - start > length_ or end == len(text_):
                passage_content = text_[start:end]
                inner_sentences.append({
                    "passage_id": self.generate_id_based_string(passage_content),
                    "passage_content": passage_content,
                    "start": start,
                    "end": end,
                })
                start = end
        if start < len(text_):
            passage_content = text_[start:]
            inner_sentences.append({
                "passage_id": self.generate_id_based_string(passage_content),
                "passage_content": passage_content,
                "start": start,
                "end": len(text_),
            })
        return inner_sentences

    def merge_sentences_split(self, doc_content: str, fix_length_list: List[int] | None = None) -> List[Dict[str, Any]]:
        fix_length_list = fix_length_list or [128, 256, 512]
        sentences: List[Dict[str, Any]] = []
        for length in fix_length_list:
            sentences += self.segment_length_by_punctuation(doc_content, length)
        return sentences

    async def split_text_by_punctuation(self, text: str, fix_length_list: List[int] | None = None, text_cutting_version: str = "punc_cutting") -> Dict[str, Any]:
        try:
            fix_length_list = fix_length_list or [128, 256, 512]
            if text_cutting_version != "punc_cutting":
                raise ValueError("text_cutting_version must be 'punc_cutting'")
            sentences_list = self.merge_sentences_split(text, fix_length_list)
            return {
                "success": True,
                "sentences_list": sentences_list,
                "total_chunks": len(sentences_list),
                "cutting_version": text_cutting_version,
                "fix_length_list": fix_length_list,
            }
        except Exception as e:
            logger.error(f"文本分割失败: {str(e)}")
            return {"success": False, "error": str(e), "sentences_list": []}