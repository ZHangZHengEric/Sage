"""
File Parser Tool for MCP Server

A tool for extracting text content from various file formats via network URLs.
Only supports network URLs for security reasons - no local file access.
"""

import hashlib
import os
import re
import tempfile
import time
import traceback
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import chardet
import requests

# 第三方库（现在由各个解析器子类处理）
# 导入新的解析器子类
from .parsers import (
    BaseFileParser,
    DOCXParser,
    EMLParser,
    ExcelParser,
    HTMLParser,
    ParseResult,
    PDFParser,
    PPTXParser,
    TextParser,
)


class FileParserError(Exception):
    """文件解析异常"""

    pass


class FileValidator:
    """文件验证器，支持本地文件和网络URL"""

    # 支持的文件类型和对应的MIME类型
    SUPPORTED_FORMATS = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".rtf": "application/rtf",
        ".eml": "message/rfc822",
    }

    # 文件大小限制 (MB)
    MAX_FILE_SIZE = {
        ".pdf": 50,
        ".docx": 25,
        ".doc": 25,
        ".pptx": 100,
        ".ppt": 100,
        ".xlsx": 25,
        ".xls": 25,
        ".txt": 10,
        ".csv": 50,
        ".json": 10,
        ".xml": 10,
        ".html": 5,
        ".htm": 5,
        ".md": 5,
        ".markdown": 5,
        ".rtf": 10,
        ".eml": 25,
    }

    @staticmethod
    def validate_file_path_or_url(file_path_or_url: str) -> Dict[str, Any]:
        """验证本地文件路径或网络URL的有效性"""
        try:
            # 检查是否为URL
            is_url = file_path_or_url.startswith(("http://", "https://"))

            if is_url:
                # URL验证逻辑
                parsed = urllib.parse.urlparse(file_path_or_url)
                if not parsed.netloc:
                    return {"valid": False, "error": "无效的URL格式"}

                # 从URL获取文件扩展名
                path = parsed.path.lower()
                file_extension = None

                for ext in FileValidator.SUPPORTED_FORMATS.keys():
                    if path.endswith(ext):
                        file_extension = ext
                        break

                if not file_extension:
                    # 尝试从URL的最后部分获取扩展名
                    filename = os.path.basename(path)
                    if "." in filename:
                        file_extension = "." + filename.split(".")[-1].lower()
                        if file_extension not in FileValidator.SUPPORTED_FORMATS:
                            return {
                                "valid": False,
                                "error": f"不支持的文件格式: {file_extension}",
                            }
                    else:
                        return {"valid": False, "error": "无法从URL确定文件类型"}

                return {
                    "valid": True,
                    "is_url": True,
                    "file_extension": file_extension,
                    "mime_type": FileValidator.SUPPORTED_FORMATS[file_extension],
                    "source": file_path_or_url,
                }
            else:
                # 本地文件路径验证逻辑
                file_path = Path(file_path_or_url)

                # 检查文件是否存在
                if not file_path.exists():
                    return {"valid": False, "error": f"文件不存在: {file_path_or_url}"}

                if not file_path.is_file():
                    return {
                        "valid": False,
                        "error": f"路径不是文件: {file_path_or_url}",
                    }

                # 获取文件扩展名
                file_extension = file_path.suffix.lower()
                if file_extension not in FileValidator.SUPPORTED_FORMATS:
                    return {
                        "valid": False,
                        "error": f"不支持的文件格式: {file_extension}",
                    }

                # 检查文件大小
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                max_size = FileValidator.MAX_FILE_SIZE.get(file_extension, 10)
                if file_size_mb > max_size:
                    return {
                        "valid": False,
                        "error": f"文件过大: {file_size_mb:.1f}MB，最大允许: {max_size}MB",
                    }

                return {
                    "valid": True,
                    "is_url": False,
                    "file_extension": file_extension,
                    "mime_type": FileValidator.SUPPORTED_FORMATS[file_extension],
                    "source": str(file_path.absolute()),
                    "file_size_mb": file_size_mb,
                }

        except Exception as e:
            return {"valid": False, "error": f"文件验证失败: {str(e)}"}


class FileHandler:
    """文件处理器，支持本地文件和网络文件下载"""

    @staticmethod
    def get_file_path(file_path_or_url: str, is_url: bool, timeout: int = 30) -> str:
        """获取文件路径，如果是URL则下载到临时目录，保持原文件名"""
        try:
            if is_url:
                # 创建临时目录
                temp_dir = tempfile.mkdtemp()

                # 从URL获取文件名，保持原文件名
                parsed_url = urllib.parse.urlparse(file_path_or_url)
                filename = os.path.basename(parsed_url.path)

                # 如果无法从URL获取文件名，生成一个
                if not filename or "." not in filename:
                    # 尝试从Content-Disposition头获取文件名
                    try:
                        response = requests.head(file_path_or_url, timeout=timeout)
                        content_disposition = response.headers.get(
                            "Content-Disposition", ""
                        )
                        if "filename=" in content_disposition:
                            filename = content_disposition.split("filename=")[1].strip(
                                '"'
                            )
                        else:
                            filename = f"downloaded_file_{int(time.time())}"
                    except:
                        filename = f"downloaded_file_{int(time.time())}"

                temp_file_path = os.path.join(temp_dir, filename)

                # 下载文件
                response = requests.get(file_path_or_url, timeout=timeout, stream=True)
                response.raise_for_status()

                with open(temp_file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                return temp_file_path
            else:
                # 本地文件，直接返回路径
                return file_path_or_url

        except Exception as e:
            raise Exception(f"文件处理失败: {str(e)}")


class TextProcessor:
    """文本处理器"""

    @staticmethod
    def clean_text(text: str) -> str:
        """清理文本内容"""
        if not text:
            return ""

        # 移除多余的空白字符
        text = re.sub(r"\n\s*\n", "\n\n", text)  # 多个连续换行符合并为双换行
        text = re.sub(r"[ \t]+", " ", text)  # 多个连续空格合并为单个空格
        text = text.strip()

        return text

    @staticmethod
    def truncate_text(text: str, start_index: int = 0, max_length: int = 5000) -> str:
        """安全地截取文本"""
        if not text:
            return ""

        start_index = max(0, start_index)
        end_index = min(len(text), start_index + max_length)

        return text[start_index:end_index]

    @staticmethod
    def get_text_stats(text: str) -> Dict[str, int]:
        """获取文本统计信息"""
        if not text:
            return {"characters": 0, "words": 0, "lines": 0, "paragraphs": 0}

        return {
            "characters": len(text),
            "words": len(text.split()),
            "lines": text.count("\n") + 1,
            "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
        }

    @staticmethod
    def replace_wrong_char(text: str, correct_dict: Dict[str, str] = None) -> str:
        """替换错误字符"""
        if not text:
            return ""

        # 默认的字符替换字典
        default_correct_dict = {
            '"': '"',
            '"': '"',
            """: "'",
            """: "'",
            "…": "...",
            "—": "-",
            "–": "-",
            "　": " ",  # 全角空格替换为半角空格
        }

        if correct_dict:
            default_correct_dict.update(correct_dict)

        for wrong_char, correct_char in default_correct_dict.items():
            text = text.replace(wrong_char, correct_char)

        return text

    @staticmethod
    def remove_duplicate_char(text: str, is_remove_wrap: bool = False) -> str:
        """移除重复字符"""
        if not text:
            return ""

        # 移除多余的换行符（连续的换行符替换为单个换行符）
        text = re.sub(r"\n+", "\n", text)

        # 移除多余的空格（连续的空格替换为单个空格）
        text = re.sub(r" +", " ", text)

        if is_remove_wrap:
            # 将换行符替换为句号
            text = text.replace("\n", "。")
            # 移除多余的句号
            text = re.sub(r"。+", "。", text)

        return text


class EncodingDetector:
    """文件编码检测器"""

    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """检测文件编码"""
        try:
            with open(file_path, "rb") as f:
                raw_data = f.read(10000)  # 读取前10KB用于检测编码
                result = chardet.detect(raw_data)
                return result["encoding"] or "utf-8"
        except Exception:
            return "utf-8"


class ParserFactory:
    """解析器工厂类"""

    def __init__(self):
        self.parsers = {
            ".pdf": PDFParser(),
            ".docx": DOCXParser(),
            ".eml": EMLParser(),
            ".pptx": PPTXParser(),
            ".xlsx": ExcelParser(),
            ".xls": ExcelParser(),
            ".html": HTMLParser(),
            ".htm": HTMLParser(),
            ".txt": TextParser(),
            ".csv": TextParser(),
            ".json": TextParser(),
            ".xml": TextParser(),
            ".md": TextParser(),
            ".markdown": TextParser(),
            ".rtf": TextParser(),
        }

    def get_parser(self, file_extension: str) -> Optional[BaseFileParser]:
        """根据文件扩展名获取对应的解析器"""
        return self.parsers.get(file_extension.lower())

    def is_supported(self, file_extension: str) -> bool:
        """检查文件类型是否支持"""
        return file_extension.lower() in self.parsers

    def detect_file_type(self, file_path: str) -> str:
        """
        检测文件的实际类型

        Args:
            file_path: 文件路径

        Returns:
            str: 检测到的文件类型扩展名
        """
        try:
            # 使用magic number检测文件类型
            import magic

            mime_type = magic.from_file(file_path, mime=True)

            # 根据MIME类型映射到扩展名
            mime_to_ext = {
                "application/pdf": ".pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                "text/plain": ".txt",
                "text/html": ".html",
                "application/json": ".json",
                "text/csv": ".csv",
                "text/markdown": ".md",
                "message/rfc822": ".eml",
            }

            detected_ext = mime_to_ext.get(mime_type, ".txt")
            print(
                f"🔍 文件类型检测: {file_path} -> MIME: {mime_type} -> 扩展名: {detected_ext}"
            )
            return detected_ext

        except ImportError:
            print("⚠️ python-magic未安装，使用文件头检测")
            return self._detect_by_header(file_path)
        except Exception as e:
            print(f"⚠️ 文件类型检测失败: {e}")
            traceback.print_exc()
            return self._detect_by_header(file_path)

    def _detect_by_header(self, file_path: str) -> str:
        """
        通过文件头检测文件类型

        Args:
            file_path: 文件路径

        Returns:
            str: 检测到的文件类型扩展名
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(1024)  # 读取前1KB

            # 检测常见文件头
            if header.startswith(b"%PDF"):
                return ".pdf"
            elif header.startswith(b"PK\x03\x04"):
                # ZIP格式，可能是DOCX, PPTX, XLSX等
                # 进一步检测
                try:
                    import zipfile

                    with zipfile.ZipFile(file_path, "r") as zip_file:
                        file_list = zip_file.namelist()
                        if "word/document.xml" in file_list:
                            return ".docx"
                        elif "ppt/presentation.xml" in file_list:
                            return ".pptx"
                        elif "xl/workbook.xml" in file_list:
                            return ".xlsx"
                except:
                    pass
                return ".txt"  # 如果无法确定，默认为文本
            elif header.startswith(b"<!DOCTYPE html") or header.startswith(b"<html"):
                return ".html"
            elif header.startswith(b"{") or header.startswith(b"["):
                return ".json"
            else:
                # 尝试检测是否为文本文件
                try:
                    header.decode("utf-8")
                    return ".txt"
                except UnicodeDecodeError:
                    try:
                        header.decode("gbk")
                        return ".txt"
                    except UnicodeDecodeError:
                        return ".txt"  # 默认为文本

        except Exception as e:
            print(f"⚠️ 文件头检测失败: {e}")
            traceback.print_exc()
            return ".txt"

    def get_smart_parser(
        self, file_path: str, file_extension: str
    ) -> tuple[Optional[BaseFileParser], bool]:
        """
        智能获取解析器，先检测实际文件类型，如果与扩展名不匹配则使用检测到的类型

        Args:
            file_path: 文件路径
            file_extension: 文件扩展名

        Returns:
            tuple[Optional[BaseFileParser], bool]: (解析器实例, 是否使用了fallback)
        """
        # 首先检测实际文件类型
        detected_ext = self.detect_file_type(file_path)
        print(f"🔍 文件扩展名: {file_extension}, 检测到的类型: {detected_ext}")

        # 如果检测到的类型与扩展名不同，优先使用检测到的类型
        if detected_ext != file_extension:
            # 如果拓展名是eml 且检测到的类型不是eml，使用拓展名
            if file_extension == ".eml" and detected_ext != ".eml":
                print(f"🔍 检测到文件类型不匹配，使用检测到的类型: {file_extension}")
                fallback_parser = self.get_parser(file_extension)
                if fallback_parser:
                    print(f"🔄 使用的解析器: {file_extension} (跳过can_parse检查)")
                    return fallback_parser, True

            print(f"🔍 检测到文件类型不匹配，使用检测到的类型: {detected_ext}")
            fallback_parser = self.get_parser(detected_ext)
            if fallback_parser:
                print(f"🔄 使用检测到的解析器: {detected_ext} (跳过can_parse检查)")
                return fallback_parser, True

        # 如果类型匹配或检测失败，使用基于扩展名的解析器
        primary_parser = self.get_parser(file_extension)
        if primary_parser:
            print(f"🔍 使用主解析器: {file_extension}")
            return primary_parser, False

        # 如果还是失败，尝试文本解析器作为最后的fallback
        print(f"🔄 使用文本解析器作为最后的fallback")
        return self.get_parser(".txt"), True


class FileParser:
    """文件解析工具"""

    def __init__(self):
        self.parser_factory = ParserFactory()

    async def extract_text_from_file(
        self,
        file_path_or_url: str,
        start_index: int = 0,
        max_length: int = 500000,
        timeout: int = 60,
        enable_text_cleaning: bool = True,
        correct_dict: Dict[str, str] = None,
        is_remove_wrap: bool = False,
    ) -> Dict[str, Any]:
        """从本地文件或网络文件提取文本内容

        Args:
            file_path_or_url: 本地文件路径或网络URL地址
            start_index: 开始提取的字符位置
            max_length: 最大提取长度
            timeout: 下载超时时间（秒）
            enable_text_cleaning: 是否启用文本清洗
            correct_dict: 自定义字符替换字典
            is_remove_wrap: 是否移除换行符

        Returns:
            包含提取结果的字典
        """
        start_time = time.time()
        operation_id = hashlib.md5(
            f"extract_{file_path_or_url}_{time.time()}".encode()
        ).hexdigest()[:8]
        temp_file_path = None

        try:
            # 验证文件路径或URL
            validation_result = FileValidator.validate_file_path_or_url(
                file_path_or_url
            )
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": validation_result["error"],
                    "source": file_path_or_url,
                    "execution_time": time.time() - start_time,
                    "operation_id": operation_id,
                }

            file_extension = validation_result["file_extension"]
            is_url = validation_result["is_url"]

            # 获取文件路径（如果是URL则下载）
            file_path = FileHandler.get_file_path(file_path_or_url, is_url, timeout)
            if is_url:
                temp_file_path = file_path  # 记录临时文件路径用于清理

            # 使用智能路由获取解析器
            parser, is_fallback = self.parser_factory.get_smart_parser(
                file_path, file_extension
            )

            if parser is None:
                # 如果没有找到任何解析器，尝试使用pandoc
                try:
                    import pypandoc

                    extracted_text = pypandoc.convert_file(file_path, "markdown")
                    parse_result = ParseResult(
                        text=extracted_text,
                        metadata={
                            "file_type": "unknown",
                            "parser": "pandoc_fallback",
                            "file_size": (
                                os.path.getsize(file_path)
                                if os.path.exists(file_path)
                                else 0
                            ),
                        },
                        success=True,
                    )
                except Exception as e:
                    print(f"Pandoc解析失败: {e}")
                    traceback.print_exc()
                    raise FileParserError(f"不支持的文件格式或解析失败: {str(e)}")
            else:
                # 使用智能选择的解析器
                try:
                    # 如果是fallback解析器，跳过格式验证
                    if is_fallback:
                        print(f"🔄 使用fallback解析器跳过格式验证: {file_path}")
                        parse_result = parser.parse(file_path, skip_validation=True)
                    else:
                        parse_result = parser.parse(file_path)

                    if not parse_result.success:
                        print(f"⚠️ 解析器失败: {parse_result.error}")
                        # 如果所有解析器都失败，尝试pypandoc
                        try:
                            import pypandoc

                            print("🔄 尝试使用pypandoc作为最后的fallback")
                            extracted_text = pypandoc.convert_file(
                                file_path, "markdown"
                            )
                            parse_result = ParseResult(
                                text=extracted_text,
                                metadata={
                                    "file_type": "unknown",
                                    "parser": "pypandoc_emergency_fallback",
                                    "file_size": (
                                        os.path.getsize(file_path)
                                        if os.path.exists(file_path)
                                        else 0
                                    ),
                                },
                                success=True,
                            )
                        except Exception as pypandoc_error:
                            raise FileParserError(
                                f"所有解析器都失败了。解析器错误: {parse_result.error}, pypandoc错误: {str(pypandoc_error)}"
                            )

                    extracted_text = parse_result.text
                except Exception as e:
                    print(f"解析器异常: {e}")
                    traceback.print_exc()

                    # 智能路由已经处理了文件类型检测，直接尝试pypandoc作为最后的fallback
                    try:
                        import pypandoc

                        print("🔄 尝试使用pypandoc作为最后的fallback")
                        extracted_text = pypandoc.convert_file(file_path, "markdown")
                        parse_result = ParseResult(
                            text=extracted_text,
                            metadata={
                                "file_type": "unknown",
                                "parser": "pypandoc_exception_fallback",
                                "file_size": (
                                    os.path.getsize(file_path)
                                    if os.path.exists(file_path)
                                    else 0
                                ),
                            },
                            success=True,
                        )
                    except Exception as pypandoc_error:
                        raise FileParserError(
                            f"所有解析器都失败了。解析器异常: {str(e)}, pypandoc错误: {str(pypandoc_error)}"
                        )

            # 处理文本
            processed_text = extracted_text

            if enable_text_cleaning:
                # 应用文本清洗
                processed_text = TextProcessor.replace_wrong_char(
                    processed_text, correct_dict
                )
                processed_text = TextProcessor.remove_duplicate_char(
                    processed_text, is_remove_wrap
                )

            # 基本清理和截取
            cleaned_text = TextProcessor.clean_text(processed_text)
            truncated_text = TextProcessor.truncate_text(
                cleaned_text, start_index, max_length
            )
            text_stats = TextProcessor.get_text_stats(cleaned_text)

            total_time = time.time() - start_time

            # 构建返回结果，包含解析器的元数据
            result = {
                "success": True,
                "text": truncated_text,
                "file_info": {
                    "source": file_path_or_url,
                    "is_url": is_url,
                    "file_extension": file_extension,
                    "mime_type": validation_result["mime_type"],
                },
                "text_info": {
                    "original_length": len(extracted_text),
                    "processed_length": len(processed_text),
                    "cleaned_length": len(cleaned_text),
                    "extracted_length": len(truncated_text),
                    "start_index": start_index,
                    "max_length": max_length,
                    "text_cleaning_enabled": enable_text_cleaning,
                    **text_stats,
                },
                "execution_time": total_time,
                "operation_id": operation_id,
            }

            # 添加解析器的元数据
            if "parse_result" in locals() and parse_result.metadata:
                result["metadata"] = parse_result.metadata

            return result

        except Exception as e:
            print(f"文件处理过程中出错: {e}")
            traceback.print_exc()
            error_time = time.time() - start_time
            return {
                "success": False,
                "error": str(e),
                "source": file_path_or_url,
                "is_url": is_url,
                "execution_time": error_time,
                "operation_id": operation_id,
            }

        finally:
            # 清理临时文件
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    async def get_supported_formats(self) -> Dict[str, Any]:
        """获取支持的文件格式列表"""
        return {
            "success": True,
            "supported_formats": FileValidator.SUPPORTED_FORMATS,
            "max_file_sizes": FileValidator.MAX_FILE_SIZE,
            "total_formats": len(FileValidator.SUPPORTED_FORMATS),
            "note": "支持网络URL和本地文件路径",
        }

    def get_supported_file_types(self) -> List[str]:
        """获取支持的文件类型列表（同步方法）"""
        return list(FileValidator.SUPPORTED_FORMATS.keys())
