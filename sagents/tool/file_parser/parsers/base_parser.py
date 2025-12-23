"""
基础文件解析器抽象类
定义统一的解析接口和返回结构
"""

import mimetypes
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class ParseResult:
    """解析结果数据类"""
    text: str
    metadata: Dict[str, Any]
    success: bool = True
    error: Optional[str] = None


class BaseFileParser(ABC):
    """基础文件解析器抽象类"""
    
    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS = []
    
    # 支持的MIME类型
    SUPPORTED_MIME_TYPES = []
    
    def __init__(self):
        """初始化解析器"""
        pass
    
    @abstractmethod
    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析文件的抽象方法
        
        Args:
            file_path: 文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）
            
        Returns:
            ParseResult: 包含解析文本和元数据的结果
        """
        pass
    
    def can_parse(self, file_path: str) -> bool:
        """
        检查是否可以解析指定文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否可以解析
        """
        # 检查文件扩展名
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext in self.SUPPORTED_EXTENSIONS:
            return True
        
        # 检查MIME类型
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and mime_type in self.SUPPORTED_MIME_TYPES:
            return True
        
        return False
    
    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        获取文件基础元数据
        
        Args:
            file_path: 文件路径
            
        Returns:
            Dict[str, Any]: 文件元数据
        """
        try:
            stat = os.stat(file_path)
            mime_type, encoding = mimetypes.guess_type(file_path)
            
            return {
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "file_extension": os.path.splitext(file_path)[1].lower(),
                "file_size": stat.st_size,
                "mime_type": mime_type,
                "encoding": encoding,
                "created_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "parser_type": self.__class__.__name__
            }
        except Exception as e:
            return {
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "file_extension": os.path.splitext(file_path)[1].lower(),
                "error": str(e),
                "parser_type": self.__class__.__name__
            }
    
    def create_error_result(self, error_message: str, file_path: str = "") -> ParseResult:
        """
        创建错误结果
        
        Args:
            error_message: 错误信息
            file_path: 文件路径
            
        Returns:
            ParseResult: 错误结果
        """
        metadata = self.get_file_metadata(file_path) if file_path else {}
        metadata["error"] = error_message
        
        return ParseResult(
            text="",
            metadata=metadata,
            success=False,
            error=error_message
        )
    
    def validate_file(self, file_path: str) -> bool:
        """
        验证文件是否存在且可读
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 文件是否有效
        """
        try:
            return os.path.isfile(file_path) and os.access(file_path, os.R_OK)
        except Exception:
            return False
    
    def _get_text_stats(self, text: str) -> Dict[str, Any]:
        """
        获取文本统计信息
        
        Args:
            text: 文本内容
            
        Returns:
            Dict[str, Any]: 文本统计信息
        """
        if not text:
            return {
                "text_length": 0,
                "character_count": 0,
                "word_count": 0,
                "line_count": 0
            }
        
        # 计算统计信息
        text_length = len(text)
        character_count = len(text.replace('\n', '').replace('\r', '').replace(' ', ''))
        word_count = len(text.split())
        line_count = text.count('\n') + 1 if text else 0
        
        return {
            "text_length": text_length,
            "character_count": character_count,
            "word_count": word_count,
            "line_count": line_count
        }