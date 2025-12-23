"""文件解析器包
包含各种文件类型的解析器实现
"""

from .base_parser import BaseFileParser, ParseResult
from .docx_parser import DOCXParser
from .eml_parser import EMLParser
from .excel_parser import ExcelParser
from .html_parser import HTMLParser
from .pdf_parser import PDFParser
from .pptx_parser import PPTXParser
from .text_parser import TextParser

__all__ = [
    'BaseFileParser', 'ParseResult',
    'PDFParser', 'DOCXParser', 'EMLParser', 'PPTXParser',
    'ExcelParser', 'HTMLParser', 'TextParser'
]