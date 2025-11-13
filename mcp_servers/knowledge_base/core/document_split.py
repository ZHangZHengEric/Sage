"""
文档分割
"""

import re
import hashlib
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class DocumentSplit:
    """文档分割工具"""

    def __init__(self):
        """初始化文档分割工具"""
        pass

    def generate_id_based_string(self, text: str, hash_fun: str = "md5") -> str:
        """
        根据字符串的内容，生成一个唯一id, 内容 -> id 是单射

        Args:
            text: 输入文本
            hash_fun: 哈希函数类型 ('md5' 或 'sha_256')

        Returns:
            生成的唯一ID
        """
        if hash_fun == "md5":
            hash_object = hashlib.md5(text.encode())
            unique_id = hash_object.hexdigest()
        elif hash_fun == "sha_256":
            # 更安全点
            hash_object = hashlib.sha256(text.encode())
            unique_id = hash_object.hexdigest()
        else:
            raise ValueError("hash_fun must be 'md5' or 'sha_256'")
        return unique_id

    def cutting_by_punctuation(self, text: str, doc_name: str) -> List[Dict[str, Any]]:
        """
        按照标点符号切割文本

        Args:
            text: 输入文本
            doc_name: 文档名称

        Returns:
            切割后的句子列表
        """
        pattern = r"[？！。]"
        sentences_list = []
        sentences = re.split(pattern, text)
        end = 0

        for i, s in enumerate(sentences):
            if i == 0:
                start, end = 0, len(s)
            else:
                start = end
                end = start + len(s)
            if len(s) > 0:
                sentences_list.append(
                    {"doc_name": doc_name, "text": s, "start": start, "end": end}
                )
        return sentences_list

    def segment_length_by_punctuation(
        self, text_: str, length_: int
    ) -> List[Dict[str, Any]]:
        """
        按照标点符号，切割后的句子，在length周围

        Args:
            text_: 输入文本
            length_: 目标长度

        Returns:
            切割后的段落列表
        """
        pattern = re.compile(r"[.。]\n?")
        positions = list(pattern.finditer(text_))
        inner_sentences = []
        start = 0

        for pos in positions:
            end = pos.end()
            if end - start > length_ or end == len(text_):
                passage_content = text_[start:end]
                inner_sentences.append(
                    {
                        "passage_id": self.generate_id_based_string(passage_content),
                        "passage_content": passage_content,
                        "start": start,
                        "end": end,
                    }
                )
                start = end

        if start < len(text_):
            passage_content = text_[start:]
            inner_sentences.append(
                {
                    "passage_id": self.generate_id_based_string(passage_content),
                    "passage_content": passage_content,
                    "start": start,
                    "end": len(text_),
                }
            )

        return inner_sentences

    def merge_sentences_split(
        self, doc_content: str, fix_length_list: List[int] = None
    ) -> List[Dict[str, Any]]:
        """
        切割逻辑是：先按照标点.。切割,将text分成一个个独立句子，
        当test:end-start大于length,就合并。

        Args:
            doc_content: 文档内容
            fix_length_list: 固定长度列表

        Returns:
            切割后的句子列表
        """
        if fix_length_list is None:
            fix_length_list = [128, 256, 512]

        if not isinstance(fix_length_list, list):
            raise ValueError("固定长度参数类型错误，必须为整数列表")

        for fl in fix_length_list:
            if not isinstance(fl, int):
                raise ValueError("固定长度列表元素参数类型错误，列表中的元素必须为整数")

        sentences = []
        for length in fix_length_list:
            sentences += self.segment_length_by_punctuation(doc_content, length)

        return sentences

    def move_window_split(
        self, doc_content: str, window_size: int = 256, stride: int = 170
    ) -> List[Dict[str, Any]]:
        """
        固定长度滑动窗口分割

        Args:
            doc_content: 文档内容
            window_size: 窗口大小
            stride: 步长

        Returns:
            切割后的句子列表
        """
        text_content = doc_content
        start, end, sentent_list = 0, window_size, []
        content_len = len(text_content)

        if content_len <= window_size:
            passage_content = text_content
            passage_id = self.generate_id_based_string(passage_content)
            sentent_list.append(
                {
                    "passage_id": passage_id,
                    "passage_content": passage_content,
                    "start": 0,
                    "end": content_len,
                }
            )
            return sentent_list

        while end < content_len:
            passage_content = text_content[start:end]
            passage_id = self.generate_id_based_string(passage_content)
            sentent_list.append(
                {
                    "passage_id": passage_id,
                    "passage_content": passage_content,
                    "start": start,
                    "end": end,
                }
            )
            start += stride
            end = start + window_size

        # 扫尾
        passage_content = text_content[start:]
        passage_id = self.generate_id_based_string(passage_content)
        end = content_len
        sentent_list.append(
            {
                "passage_id": passage_id,
                "passage_content": passage_content,
                "start": start,
                "end": end,
            }
        )

        return sentent_list

    async def split_text_by_punctuation(
        self,
        text: str,
        fix_length_list: List[int] = None,
        text_cutting_version: str = "punc_cutting",
    ) -> Dict[str, Any]:
        """
        按标点符号分割文本

        Args:
            text: 要分割的文本
            fix_length_list: 固定长度列表，默认 [128, 256, 512]
            text_cutting_version: 分割版本，支持 'punc_cutting'

        Returns:
            分割结果
        """
        try:
            if fix_length_list is None:
                fix_length_list = [128, 256, 512]

            if text_cutting_version == "punc_cutting":
                sentences_list = self.merge_sentences_split(text, fix_length_list)
            else:
                raise ValueError("text_cutting_version must be 'punc_cutting'")

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

    async def split_text_by_sliding_window(
        self, text: str, window_size: int = 256, stride: int = 170
    ) -> Dict[str, Any]:
        """
        使用滑动窗口分割文本

        Args:
            text: 要分割的文本
            window_size: 窗口大小，默认 256
            stride: 步长，默认 170

        Returns:
            分割结果
        """
        try:
            sentences_list = self.move_window_split(text, window_size, stride)

            return {
                "success": True,
                "sentences_list": sentences_list,
                "total_chunks": len(sentences_list),
                "cutting_version": "move_window_cutting",
                "window_size": window_size,
                "stride": stride,
            }

        except Exception as e:
            logger.error(f"滑动窗口文本分割失败: {str(e)}")
            return {"success": False, "error": str(e), "sentences_list": []}
