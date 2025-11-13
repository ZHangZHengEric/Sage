"""
纯文本文件解析器
支持各种文本文件的解析和元数据获取
"""

import traceback
import chardet
import re
from typing import Dict, Any, List
from .base_parser import BaseFileParser, ParseResult


class TextParser(BaseFileParser):
    """纯文本文件解析器"""
    
    SUPPORTED_EXTENSIONS = [
        '.txt', '.md', '.markdown', '.rst', '.log', '.csv', '.tsv',
        '.json', '.xml', '.yaml', '.yml', '.ini', '.cfg', '.conf',
        '.py', '.js', '.html', '.css', '.sql', '.sh', '.bat',
        '.c', '.cpp', '.h', '.hpp', '.java', '.php', '.rb', '.go',
        '.rs', '.swift', '.kt', '.scala', '.r', '.m', '.pl'
    ]
    SUPPORTED_MIME_TYPES = [
        'text/plain', 'text/markdown', 'text/csv', 'text/tab-separated-values',
        'application/json', 'text/xml', 'application/xml', 'text/yaml',
        'text/x-python', 'text/javascript', 'text/css', 'text/sql'
    ]
    
    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析文本文件
        
        Args:
            file_path: 文本文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）
            
        Returns:
            ParseResult: 解析结果
        """
        if not self.validate_file(file_path):
            return self.create_error_result(f"文件不存在或无法读取: {file_path}", file_path)
        
        if not skip_validation and not self.can_parse(file_path):
            return self.create_error_result(f"不支持的文件类型: {file_path}", file_path)
        
        return self._do_parse(file_path)
    
    def _do_parse(self, file_path: str) -> ParseResult:
        """
        实际的解析逻辑
        
        Args:
            file_path: 文本文件路径
            
        Returns:
            ParseResult: 解析结果
        """
        try:
            # 检测文件编码
            encoding = self._detect_encoding(file_path)
            
            # 读取文件内容
            with open(file_path, 'r', encoding=encoding, errors='ignore') as file:
                text = file.read()
            
            # 获取基础文件元数据
            base_metadata = self.get_file_metadata(file_path)
            
            # 获取文本特定元数据
            text_metadata = self._extract_text_metadata(text, file_path, encoding)
            
            # 合并元数据
            metadata = {**base_metadata, **text_metadata}
            
            # 添加文本统计信息
            metadata.update({
                "text_length": len(text),
                "character_count": len(text),
                "word_count": len(text.split()) if text else 0,
                "line_count": text.count('\\n') + 1 if text else 0
            })
            
            return ParseResult(
                text=text,
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            error_msg = f"文本解析失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return self.create_error_result(error_msg, file_path)
    
    def _detect_encoding(self, file_path: str) -> str:
        """
        检测文件编码
        
        Args:
            file_path: 文件路径
            
        Returns:
            str: 检测到的编码
        """
        try:
            with open(file_path, 'rb') as file:
                raw_data = file.read(10000)  # 读取前10KB用于检测
                result = chardet.detect(raw_data)
                encoding = result.get('encoding', 'utf-8')
                confidence = result.get('confidence', 0)
                
                # 如果置信度太低，使用默认编码
                if confidence < 0.7:
                    encoding = 'utf-8'
                
                return encoding
        except Exception as e:
            print(f"编码检测失败，使用默认编码: {e}")
            return 'utf-8'
    
    def _extract_text_metadata(self, text: str, file_path: str, encoding: str) -> Dict[str, Any]:
        """
        提取文本特定元数据
        
        Args:
            text: 文本内容
            file_path: 文件路径
            encoding: 文件编码
            
        Returns:
            Dict[str, Any]: 文本元数据
        """
        try:
            metadata = {
                "encoding": encoding,
                "file_type": self._detect_file_type(file_path, text)
            }
            
            if text:
                # 基本统计
                lines = text.split('\\n')
                metadata.update({
                    "total_lines": len(lines),
                    "non_empty_lines": len([line for line in lines if line.strip()]),
                    "empty_lines": len([line for line in lines if not line.strip()]),
                    "max_line_length": max(len(line) for line in lines) if lines else 0,
                    "min_line_length": min(len(line) for line in lines) if lines else 0,
                    "average_line_length": sum(len(line) for line in lines) / len(lines) if lines else 0
                })
                
                # 字符统计
                metadata.update({
                    "alphabetic_chars": sum(1 for c in text if c.isalpha()),
                    "numeric_chars": sum(1 for c in text if c.isdigit()),
                    "whitespace_chars": sum(1 for c in text if c.isspace()),
                    "punctuation_chars": sum(1 for c in text if not c.isalnum() and not c.isspace()),
                    "uppercase_chars": sum(1 for c in text if c.isupper()),
                    "lowercase_chars": sum(1 for c in text if c.islower())
                })
                
                # 语言检测（简单的启发式方法）
                metadata["detected_language"] = self._detect_language(text)
                
                # 特殊内容检测
                metadata.update({
                    "contains_urls": bool(re.search(r'https?://[^\\s]+', text)),
                    "contains_emails": bool(re.search(r'\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b', text)),
                    "contains_phone_numbers": bool(re.search(r'\\b\\d{3}[-.]?\\d{3}[-.]?\\d{4}\\b', text)),
                    "contains_dates": bool(re.search(r'\\b\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}\\b', text)),
                    "contains_numbers": bool(re.search(r'\\b\\d+\\b', text))
                })
                
                # 根据文件类型提取特定信息
                file_type = metadata["file_type"]
                if file_type == "code":
                    metadata.update(self._analyze_code_file(text, file_path))
                elif file_type == "csv":
                    metadata.update(self._analyze_csv_file(text))
                elif file_type == "json":
                    metadata.update(self._analyze_json_file(text))
                elif file_type == "markdown":
                    metadata.update(self._analyze_markdown_file(text))
                elif file_type == "log":
                    metadata.update(self._analyze_log_file(text))
            
            return metadata
            
        except Exception as e:
            print(f"提取文本元数据时出错: {e}")
            traceback.print_exc()
            return {"metadata_extraction_error": str(e)}
    
    def _detect_file_type(self, file_path: str, text: str) -> str:
        """
        检测文件类型
        
        Args:
            file_path: 文件路径
            text: 文件内容
            
        Returns:
            str: 文件类型
        """
        extension = file_path.lower().split('.')[-1] if '.' in file_path else ''
        
        # 代码文件
        code_extensions = ['py', 'js', 'html', 'css', 'sql', 'sh', 'bat', 'c', 'cpp', 'h', 'hpp', 
                          'java', 'php', 'rb', 'go', 'rs', 'swift', 'kt', 'scala', 'r', 'm', 'pl']
        if extension in code_extensions:
            return "code"
        
        # 数据文件
        if extension in ['csv', 'tsv']:
            return "csv"
        elif extension in ['json']:
            return "json"
        elif extension in ['xml']:
            return "xml"
        elif extension in ['yaml', 'yml']:
            return "yaml"
        
        # 文档文件
        elif extension in ['md', 'markdown']:
            return "markdown"
        elif extension in ['rst']:
            return "restructuredtext"
        
        # 配置文件
        elif extension in ['ini', 'cfg', 'conf']:
            return "config"
        
        # 日志文件
        elif extension in ['log'] or 'log' in file_path.lower():
            return "log"
        
        # 默认为纯文本
        else:
            return "plain_text"
    
    def _detect_language(self, text: str) -> str:
        """
        简单的语言检测
        
        Args:
            text: 文本内容
            
        Returns:
            str: 检测到的语言
        """
        # 简单的启发式语言检测
        chinese_chars = sum(1 for c in text if '\\u4e00' <= c <= '\\u9fff')
        total_chars = len(text)
        
        if total_chars > 0:
            chinese_ratio = chinese_chars / total_chars
            if chinese_ratio > 0.1:
                return "chinese"
        
        return "english"  # 默认为英语
    
    def _analyze_code_file(self, text: str, file_path: str) -> Dict[str, Any]:
        """分析代码文件"""
        extension = file_path.lower().split('.')[-1] if '.' in file_path else ''
        lines = text.split('\\n')
        
        return {
            "programming_language": extension,
            "comment_lines": len([line for line in lines if line.strip().startswith('#') or line.strip().startswith('//')]),
            "blank_lines": len([line for line in lines if not line.strip()]),
            "code_lines": len([line for line in lines if line.strip() and not line.strip().startswith('#') and not line.strip().startswith('//')])
        }
    
    def _analyze_csv_file(self, text: str) -> Dict[str, Any]:
        """分析CSV文件"""
        lines = text.split('\\n')
        non_empty_lines = [line for line in lines if line.strip()]
        
        if non_empty_lines:
            # 检测分隔符
            first_line = non_empty_lines[0]
            comma_count = first_line.count(',')
            tab_count = first_line.count('\\t')
            semicolon_count = first_line.count(';')
            
            if tab_count > comma_count and tab_count > semicolon_count:
                delimiter = 'tab'
                column_count = tab_count + 1
            elif semicolon_count > comma_count:
                delimiter = 'semicolon'
                column_count = semicolon_count + 1
            else:
                delimiter = 'comma'
                column_count = comma_count + 1
            
            return {
                "delimiter": delimiter,
                "estimated_columns": column_count,
                "data_rows": len(non_empty_lines) - 1,  # 假设第一行是标题
                "has_header": True
            }
        
        return {"delimiter": "unknown", "estimated_columns": 0, "data_rows": 0}
    
    def _analyze_json_file(self, text: str) -> Dict[str, Any]:
        """分析JSON文件"""
        try:
            import json
            data = json.loads(text)
            
            def count_elements(obj):
                if isinstance(obj, dict):
                    return sum(count_elements(v) for v in obj.values()) + len(obj)
                elif isinstance(obj, list):
                    return sum(count_elements(item) for item in obj) + len(obj)
                else:
                    return 1
            
            return {
                "is_valid_json": True,
                "root_type": type(data).__name__,
                "total_elements": count_elements(data),
                "max_depth": self._get_json_depth(data)
            }
        except:
            return {"is_valid_json": False}
    
    def _get_json_depth(self, obj, depth=0):
        """计算JSON深度"""
        if isinstance(obj, dict):
            return max([self._get_json_depth(v, depth + 1) for v in obj.values()], default=depth)
        elif isinstance(obj, list):
            return max([self._get_json_depth(item, depth + 1) for item in obj], default=depth)
        else:
            return depth
    
    def _analyze_markdown_file(self, text: str) -> Dict[str, Any]:
        """分析Markdown文件"""
        lines = text.split('\\n')
        
        heading_counts = {}
        for i in range(1, 7):
            heading_counts[f"h{i}"] = len([line for line in lines if line.strip().startswith('#' * i + ' ')])
        
        return {
            "heading_counts": heading_counts,
            "code_blocks": text.count('```'),
            "links": len(re.findall(r'\\[.*?\\]\\(.*?\\)', text)),
            "images": len(re.findall(r'!\\[.*?\\]\\(.*?\\)', text)),
            "bold_text": len(re.findall(r'\\*\\*.*?\\*\\*', text)),
            "italic_text": len(re.findall(r'\\*.*?\\*', text))
        }
    
    def _analyze_log_file(self, text: str) -> Dict[str, Any]:
        """分析日志文件"""
        lines = text.split('\\n')
        
        # 检测日志级别
        error_lines = len([line for line in lines if re.search(r'\\b(ERROR|FATAL)\\b', line, re.IGNORECASE)])
        warning_lines = len([line for line in lines if re.search(r'\\bWARN(ING)?\\b', line, re.IGNORECASE)])
        info_lines = len([line for line in lines if re.search(r'\\bINFO\\b', line, re.IGNORECASE)])
        debug_lines = len([line for line in lines if re.search(r'\\bDEBUG\\b', line, re.IGNORECASE)])
        
        # 检测时间戳
        timestamp_lines = len([line for line in lines if re.search(r'\\d{4}-\\d{2}-\\d{2}|\\d{2}/\\d{2}/\\d{4}', line)])
        
        return {
            "error_lines": error_lines,
            "warning_lines": warning_lines,
            "info_lines": info_lines,
            "debug_lines": debug_lines,
            "timestamp_lines": timestamp_lines,
            "has_timestamps": timestamp_lines > 0
        }