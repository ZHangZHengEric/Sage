"""
EML文件解析器
支持邮件文件的文本提取和元数据获取
"""

import asyncio
import concurrent.futures
import email
import email.utils
import os
import tempfile
import traceback
from email import policy
from email.feedparser import headerRE
from email.header import decode_header
from typing import Any, Dict, List, Tuple

import chardet
import html2text

from .base_parser import BaseFileParser, ParseResult

# 尝试导入flanker，如果没有则使用email.utils作为备选
try:
    from flanker.addresslib import address

    HAS_FLANKER = True
except ImportError:
    HAS_FLANKER = False
    print("Warning: flanker not available, using email.utils for address parsing")

# 尝试导入OpenCC，如果没有则跳过繁简转换
try:
    from opencc import OpenCC

    convert = OpenCC("tw2s").convert
    HAS_OPENCC = True
except ImportError:
    HAS_OPENCC = False
    def convert(x): return x  # 如果没有OpenCC，直接返回原文
    print(
        "Warning: OpenCC not available, skipping traditional to simplified conversion"
    )


class EMLParser(BaseFileParser):
    """EML文件解析器"""

    SUPPORTED_EXTENSIONS = [".eml"]
    SUPPORTED_MIME_TYPES = ["message/rfc822", "text/plain"]

    def __init__(self):
        super().__init__()
        self.flanker_available = HAS_FLANKER
        self._raw_email_content = None  # 保存原始邮件内容
        self.opencc_available = HAS_OPENCC

    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析EML文件

        Args:
            file_path: EML文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）

        Returns:
            ParseResult: 解析结果
        """
        if not self.validate_file(file_path):
            return self.create_error_result(
                f"文件不存在或无法读取: {file_path}", file_path
            )

        if not skip_validation and not self.can_parse(file_path):
            return self.create_error_result(f"不支持的文件类型: {file_path}", file_path)

        try:
            # 使用参考实现的文件读取逻辑
            eml_content = self._read_eml_file(file_path)

            # 预处理EML内容，移除SMTP头部
            eml_content = self._preprocess_eml_content(eml_content)

            # 保存原始邮件内容，用于容错处理
            self._raw_email_content = eml_content

            # 解析邮件消息
            msg = email.message_from_string(eml_content, policy=policy.default)

            # 提取邮件内容和元数据
            text, eml_metadata = self._extract_email_content(msg)

            # 合并基础元数据和EML特定元数据
            base_metadata = self.get_file_metadata(file_path)
            metadata = {**base_metadata, **eml_metadata}

            # 添加文本统计信息
            metadata.update(
                {
                    "text_length": len(text),
                    "character_count": len(text),
                    "word_count": len(text.split()) if text else 0,
                    "line_count": text.count("\n") if text else 0,
                }
            )

            return ParseResult(text=text, metadata=metadata, success=True)

        except Exception as e:
            error_msg = f"EML解析失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return self.create_error_result(error_msg, file_path)

    def _read_eml_file(self, file_path: str) -> str:
        """
        读取EML文件，尝试多种编码
        参考原始实现的编码检测逻辑
        """
        encoding_types = ["utf-8", "big5", "gbk", "gb2312"]
        eml_content = None

        for encoding in encoding_types:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    eml_content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if eml_content is None:
            # 最后尝试用utf-8忽略错误
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                eml_content = f.read()

        return eml_content

    def _preprocess_eml_content(self, eml_content: str) -> str:
        """
        预处理EML内容，移除SMTP头部，找到真正的邮件头开始位置
        参考原始实现的预处理逻辑
        """
        eml_content_lines = eml_content.split("\n")
        start_index = 0
        end_index = len(eml_content_lines)

        # 找到邮件头的开始位置
        for index, line in enumerate(eml_content_lines):
            if headerRE.match(line):
                start_index = index
                break

        return "\n".join(eml_content_lines[start_index:end_index])

    def _extract_email_content(
        self, msg: email.message.Message
    ) -> Tuple[str, Dict[str, Any]]:
        """
        提取邮件内容和元数据，使用增强的元数据提取逻辑

        Args:
            msg: 邮件消息对象

        Returns:
            Tuple[str, Dict[str, Any]]: (文本内容, 元数据)
        """
        try:
            # 使用新的增强元数据提取方法
            enhanced_metadata = self._extract_metadata(msg)

            # 直接使用enhanced_metadata中已解析的地址信息，避免重复解析
            sender = enhanced_metadata.get("sender", "")
            sender_name = enhanced_metadata.get("sender_name", "")
            sender_address = enhanced_metadata.get("sender_address", sender)

            receiver = enhanced_metadata.get("receiver", "")
            receiver_names = enhanced_metadata.get("receiver_names", [""])
            receiver_addresses = enhanced_metadata.get(
                "receiver_addresses", [receiver] if receiver else []
            )

            # 处理日期格式
            date = enhanced_metadata.get("date", "")
            if date:
                try:
                    from datetime import datetime
                    from email.utils import parsedate_to_datetime

                    date_obj = parsedate_to_datetime(date)
                    date_str = datetime.strftime(date_obj, "%Y-%m-%d %H:%M:%S")
                    date = convert(date_str)
                except Exception as e:
                    print(f"解析日期时出错: {e}")
                    date = convert(date)

            # 获取其他字段
            cc = enhanced_metadata.get("cc", "")
            subject = enhanced_metadata.get("subject", "")
            body = enhanced_metadata.get("body", "")
            attachments = enhanced_metadata.get("attachments", [])

            # 构建文本内容
            text_parts = [
                "发件人：" + sender,
                "收件人：" + receiver,
                "抄送：" + cc,
                "邮件主题：" + subject,
                "收发讯息时间：" + date,
                "邮件正文："
                + (
                    body.get("text_content", "")
                    if isinstance(body, dict)
                    else str(body)
                ),
            ]
            text = "\n".join(text_parts)

            # 构建完整的元数据（保持向后兼容）
            metadata = {
                "sender": sender,
                "receiver": receiver,
                "sender_name": sender_name,
                "sender_address": sender_address,
                "receiver_names": receiver_names,
                "receiver_addresses": receiver_addresses,
                "cc": cc,
                "cc_names": [],  # 可以后续扩展
                "cc_addresses": [],  # 可以后续扩展
                "bcc": "",  # EML文件通常不包含BCC信息
                "bcc_names": [],
                "bcc_addresses": [],
                "date": date,
                "subject": subject,
                "message_id": enhanced_metadata.get("message_id", ""),
                "body": body,
                "attachments": attachments if isinstance(attachments, list) else [],
                "attachment_files": (
                    attachments if isinstance(attachments, list) else []
                ),
                "attachment_images": [],  # 可以后续从attachments中分离
                "attachment_count": (
                    len(attachments) if isinstance(attachments, list) else 0
                ),
                "has_attachments": (
                    len(attachments) > 0 if isinstance(attachments, list) else False
                ),
                "content_type": msg.get_content_type(),
                "charset": msg.get_charset(),
                "is_multipart": msg.is_multipart(),
            }

            return text, metadata

        except Exception as e:
            print(f"提取邮件内容时出错: {e}")
            traceback.print_exc()
            return "", {"extraction_error": str(e)}

    def _safe_get_header(self, msg: email.message.Message, header_name: str) -> str:
        """
        安全获取邮件头信息，支持编码解码和容错处理
        """
        try:
            # 首先尝试正常获取
            header_value = msg.get(header_name, "")
            if header_value:
                # 先清理CR/LF字符，避免地址解析错误
                cleaned_header = (
                    header_value.replace("\r", "").replace("\n", " ").strip()
                )
                # 解码邮件头
                decoded_header = self._decode_header(cleaned_header)
                # 转换繁体到简体
                return convert(decoded_header)
            return ""
        except Exception as e:
            print(f"获取邮件头 {header_name} 时出错: {e}")
            traceback.print_exc()
            # 容错处理：使用原始字符串方式获取头信息
            try:
                # 获取原始邮件字符串，直接解析头部
                raw_header = self._get_raw_header(msg, header_name)
                if raw_header:
                    # 清理CR/LF字符
                    cleaned_header = (
                        raw_header.replace("\r", "").replace("\n", " ").strip()
                    )
                    # 解码邮件头
                    decoded_header = self._decode_header(cleaned_header)
                    # 转换繁体到简体
                    return convert(decoded_header)
                return ""
            except Exception as e2:
                print(f"容错获取邮件头 {header_name} 也失败: {e2}")
                return ""

    def _get_raw_header(self, msg: email.message.Message, header_name: str) -> str:
        """
        直接从原始邮件字符串中获取头信息，避免email库的CR/LF检查
        """
        try:
            # 使用保存的原始邮件内容
            if not self._raw_email_content:
                return ""

            lines = self._raw_email_content.split("\n")

            # 查找指定的头部
            header_pattern = f"{header_name}:"
            header_value = ""
            found_header = False

            for i, line in enumerate(lines):
                # 检查是否是目标头部的开始
                if line.lower().startswith(header_pattern.lower()):
                    found_header = True
                    # 获取头部值（去掉头部名称和冒号）
                    header_value = line[len(header_pattern):].strip()

                    # 检查后续行是否是续行（以空格或制表符开始）
                    j = i + 1
                    while j < len(lines) and (
                        lines[j].startswith(" ") or lines[j].startswith("\t")
                    ):
                        header_value += " " + lines[j].strip()
                        j += 1
                    break

                # 如果遇到空行，说明头部结束了
                if not line.strip():
                    break

            return header_value if found_header else ""

        except Exception as e:
            print(f"原始头部解析失败 {header_name}: {e}")
            return ""

    def _decode_payload_part(self, part: email.message.Message) -> str:
        """
        解码邮件部分的载荷
        """
        try:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                return self._smart_decode(payload, charset)
            elif isinstance(payload, str):
                return payload
            else:
                return str(payload) if payload else ""
        except Exception as e:
            print(f"解码邮件部分失败: {e}")
            return ""

    def _extract_subject_from_body(self, msg: email.message.Message) -> str:
        """
        从邮件体中尝试提取主题信息（当Subject字段缺失时）
        """
        try:
            # 获取邮件的第一部分文本内容
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        content = self._decode_payload_part(part)
                        # 查找可能的主题行
                        lines = content.split("\n")[:5]  # 只检查前5行
                        for i, line in enumerate(lines):
                            line = line.strip()
                            if line and len(line) < 100:  # 主题通常不会太长
                                # 检查是否包含主题关键词
                                if any(
                                    keyword in line.lower()
                                    for keyword in [
                                        "re:",
                                        "fw:",
                                        "fwd:",
                                        "主题:",
                                        "标题:",
                                    ]
                                ):
                                    return line
                                # 如果是第一行非空内容，可能是主题
                                if i == 0:
                                    return line
                        break
            else:
                content = self._decode_payload_part(msg)
                lines = content.split("\n")[:3]
                for line in lines:
                    line = line.strip()
                    if line and len(line) < 100:
                        return line
        except Exception as e:
            print(f"从邮件体提取主题时出错: {e}")

        return ""

    def _generate_fallback_message_id(self, msg: email.message.Message) -> str:
        """
        当Message-ID缺失时，生成一个备用的标识符
        """
        try:
            import hashlib
            from datetime import datetime

            # 收集可用的信息来生成唯一标识
            components = []

            # 添加发件人
            sender = msg.get("From", "")
            if sender:
                components.append(sender)

            # 添加收件人
            receiver = msg.get("To", "")
            if receiver:
                components.append(receiver)

            # 添加主题
            subject = msg.get("Subject", "")
            if subject:
                components.append(subject)

            # 添加日期
            date = msg.get("Date", "")
            if date:
                components.append(date)
            else:
                # 如果没有日期，使用当前时间
                components.append(datetime.now().isoformat())

            # 如果有内容，添加内容的一部分
            try:
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            content = self._decode_payload_part(part)
                            if content and len(content) > 10:
                                components.append(content[:100])  # 只取前100个字符
                            break
                else:
                    content = self._decode_payload_part(msg)
                    if content and len(content) > 10:
                        components.append(content[:100])
            except Exception:
                pass

            # 生成哈希值作为备用Message-ID
            if components:
                combined = "|".join(components)
                hash_value = hashlib.md5(combined.encode("utf-8")).hexdigest()
                return f"<fallback-{hash_value}@eml-parser>"
            else:
                # 如果没有任何信息，使用时间戳
                timestamp = datetime.now().timestamp()
                return f"<fallback-{timestamp}@eml-parser>"

        except Exception as e:
            print(f"生成备用Message-ID时出错: {e}")
            # 最后的容错处理
            import time

            return f"<fallback-{int(time.time())}@eml-parser>"

    def _smart_decode(self, data: bytes, charset: str = None) -> str:
        """
        智能解码，支持多种编码格式
        """
        if isinstance(data, str):
            return data

        # 扩展编码映射
        encoding_map = {
            "gb2312": "gbk",
            "gb18030": "gbk",
            "big5": "big5",
            "utf-8": "utf-8",
            "utf8": "utf-8",
            "iso-8859-1": "latin-1",
            "ascii": "ascii",
        }

        # 优先使用指定的字符集
        if charset:
            charset_lower = charset.lower().strip()
            if charset_lower in encoding_map:
                try:
                    decoded = data.decode(encoding_map[charset_lower], errors="ignore")
                    if self._is_valid_decoded_text(decoded):
                        return decoded
                except (UnicodeDecodeError, LookupError):
                    pass

        # 使用chardet检测编码
        try:
            detected = chardet.detect(data)
            if detected and detected.get("confidence", 0) > 0.7:
                detected_encoding = detected["encoding"]
                if detected_encoding:
                    decoded = data.decode(detected_encoding, errors="ignore")
                    if self._is_valid_decoded_text(decoded):
                        return decoded
        except Exception:
            pass

        # 常见编码回退
        common_encodings = ["utf-8", "gbk", "big5", "latin-1", "ascii"]
        for encoding in common_encodings:
            try:
                decoded = data.decode(encoding, errors="ignore")
                if self._is_valid_decoded_text(decoded):
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue

        # 最后回退到latin-1
        return data.decode("latin-1", errors="ignore")

    def _is_valid_decoded_text(self, text: str) -> bool:
        """
        检查解码后的文本质量
        """
        if not text:
            return False

        # 计算乱码字符比例
        garbled_chars = sum(1 for char in text if ord(char) in [0xFFFD, 0xFEFF])
        total_chars = len(text)

        if total_chars == 0:
            return False

        garbled_ratio = garbled_chars / total_chars
        return garbled_ratio < 0.1  # 乱码字符少于10%认为是有效的

    def _decode_header(self, header_value: str) -> str:
        """
        解码邮件头信息

        Args:
            header_value: 头信息值

        Returns:
            str: 解码后的字符串
        """
        if not header_value:
            return ""

        try:
            decoded_parts = decode_header(header_value)
            decoded_string = ""

            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        try:
                            decoded_string += part.decode(encoding)
                        except (UnicodeDecodeError, LookupError):
                            # 尝试其他编码
                            for fallback_encoding in [
                                "utf-8",
                                "gbk",
                                "gb2312",
                                "latin1",
                            ]:
                                try:
                                    decoded_string += part.decode(fallback_encoding)
                                    break
                                except (UnicodeDecodeError, LookupError):
                                    continue
                            else:
                                decoded_string += part.decode("utf-8", errors="ignore")
                    else:
                        decoded_string += part.decode("utf-8", errors="ignore")
                else:
                    decoded_string += str(part)

            return decoded_string
        except Exception as e:
            print(f"解码邮件头时出错: {e}")
            traceback.print_exc()
            return header_value

    def _parse_email_address(self, address_str: str) -> Tuple[str, str]:
        """
        解析单个邮件地址

        Args:
            address_str: 邮件地址字符串

        Returns:
            Tuple[str, str]: (姓名, 邮件地址)
        """
        if not address_str:
            return "", ""

        try:
            # 清理地址字符串中的回车和换行符
            clean_address_str = address_str.replace("\r", "").replace("\n", " ").strip()
            name, addr = email.utils.parseaddr(clean_address_str)
            return name.strip(), addr.strip()
        except Exception:
            clean_str = address_str.replace("\r", "").replace("\n", " ").strip()
            return "", clean_str

    def _parse_email_addresses(self, addresses_str: str) -> Tuple[List[str], List[str]]:
        """
        解析多个邮件地址

        Args:
            addresses_str: 邮件地址字符串

        Returns:
            Tuple[List[str], List[str]]: (姓名列表, 邮件地址列表)
        """
        if not addresses_str:
            return [], []

        try:
            # 清理地址字符串中的回车和换行符
            clean_addresses_str = (
                addresses_str.replace("\r", "").replace("\n", " ").strip()
            )
            addresses = email.utils.getaddresses([clean_addresses_str])
            names = [name.strip() for name, addr in addresses]
            addrs = [addr.strip() for name, addr in addresses]
            return names, addrs
        except Exception as e:
            print(f"解析邮件地址时出错: {e}")
            print(f"原始地址字符串: {repr(addresses_str)}")
            # 如果解析失败，尝试简单清理后返回
            clean_str = addresses_str.replace("\r", "").replace("\n", " ").strip()
            return [], [clean_str] if clean_str else []

    def _extract_body(self, msg: email.message.Message) -> Dict[str, str]:
        """
        提取邮件正文，支持多种格式和编码，增强验证机制
        """
        try:
            body_data = {
                "text_content": "",
                "html_content": "",
                "raw_content": "",
                "content_type": "",
                "charset": "",
                "encoding_issues": [],
            }

            if msg.is_multipart():
                # 处理多部分邮件
                text_parts = []
                html_parts = []

                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue

                    content_type = part.get_content_type()
                    charset = part.get_content_charset() or "utf-8"

                    # 获取原始payload
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    # 智能解码
                    try:
                        decoded_content = self._smart_decode(payload, charset)

                        # 验证解码质量
                        if not self._is_valid_decoded_text(decoded_content):
                            body_data["encoding_issues"].append(
                                f"解码质量问题: {content_type}"
                            )

                        # 根据内容类型分类
                        if content_type == "text/plain":
                            text_parts.append(decoded_content)
                        elif content_type == "text/html":
                            html_parts.append(decoded_content)
                            # 将HTML转换为文本作为备选
                            try:
                                text_from_html = self._html2txt(decoded_content)
                                if text_from_html and len(text_from_html.strip()) > 0:
                                    text_parts.append(text_from_html)
                            except Exception as e:
                                print(f"HTML转文本失败: {e}")
                        else:
                            # 其他类型的文本内容
                            if content_type.startswith("text/"):
                                text_parts.append(decoded_content)

                    except Exception as e:
                        print(f"解码邮件部分失败: {e}")
                        body_data["encoding_issues"].append(
                            f"解码失败: {content_type} - {str(e)}"
                        )
                        continue

                # 合并内容
                body_data["text_content"] = "\n\n".join(text_parts).strip()
                body_data["html_content"] = "\n\n".join(html_parts).strip()

            else:
                # 处理单部分邮件
                content_type = msg.get_content_type()
                charset = msg.get_content_charset() or "utf-8"

                payload = msg.get_payload(decode=True)
                if payload:
                    try:
                        decoded_content = self._smart_decode(payload, charset)

                        # 验证解码质量
                        if not self._is_valid_decoded_text(decoded_content):
                            body_data["encoding_issues"].append(
                                f"解码质量问题: {content_type}"
                            )

                        if content_type == "text/html":
                            body_data["html_content"] = decoded_content
                            # 转换HTML为文本
                            try:
                                body_data["text_content"] = self._html2txt(
                                    decoded_content
                                )
                            except Exception as e:
                                print(f"HTML转文本失败: {e}")
                                body_data["text_content"] = decoded_content
                        else:
                            body_data["text_content"] = decoded_content

                    except Exception as e:
                        print(f"解码邮件内容失败: {e}")
                        body_data["encoding_issues"].append(f"解码失败: {str(e)}")
                        # 尝试强制解码
                        try:
                            body_data["text_content"] = payload.decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            body_data["text_content"] = str(payload, errors="replace")

            # 设置元数据
            body_data["content_type"] = msg.get_content_type()
            body_data["charset"] = msg.get_content_charset() or "utf-8"
            body_data["raw_content"] = (
                body_data["text_content"] or body_data["html_content"]
            )

            # 清理和验证内容
            body_data["text_content"] = self._clean_and_validate_content(
                body_data["text_content"]
            )
            body_data["html_content"] = self._clean_and_validate_content(
                body_data["html_content"]
            )

            return body_data

        except Exception as e:
            print(f"提取邮件正文失败: {e}")
            import traceback

            traceback.print_exc()
            return {
                "text_content": "",
                "html_content": "",
                "raw_content": "",
                "content_type": "",
                "charset": "",
                "encoding_issues": [f"提取失败: {str(e)}"],
            }

    def _clean_and_validate_content(self, content: str) -> str:
        """
        清理和验证内容，移除乱码和无效字符
        """
        if not content:
            return ""

        # 移除常见的乱码字符
        import re

        # 移除替换字符和BOM
        content = content.replace("\ufffd", "").replace("\ufeff", "")

        # 移除过多的空白字符
        content = re.sub(r"\n\s*\n\s*\n", "\n\n", content)
        content = re.sub(r"[ \t]+", " ", content)

        # 移除控制字符（保留换行、回车、制表符）
        content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)

        # 验证内容质量
        if len(content.strip()) == 0:
            return ""

        # 检查是否包含有意义的文本
        meaningful_chars = re.sub(r"[\s\n\r\t]", "", content)
        if len(meaningful_chars) < 3:  # 至少3个有意义的字符
            return ""

        return content.strip()

    def _decode_payload(self, payload: bytes, charset: str) -> str:
        """
        解码邮件载荷

        Args:
            payload: 字节载荷
            charset: 字符编码

        Returns:
            str: 解码后的字符串
        """
        if not payload:
            return ""

        if charset:
            try:
                return payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                pass

        # 尝试常见编码
        for encoding in ["utf-8", "gbk", "gb2312", "latin1"]:
            try:
                return payload.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue

        # 最后使用忽略错误的UTF-8解码
        return payload.decode("utf-8", errors="ignore")

    def _extract_attachments(self, msg: email.message.Message) -> Dict[str, Any]:
        """
        提取邮件附件
        参考原始实现的get_attachment方法

        Args:
            msg: 邮件消息对象

        Returns:
            Dict[str, Any]: 附件信息字典，包含files和images列表
        """
        attachment = {
            "files": [],
            "images": [],
        }

        try:
            for attach in msg.iter_attachments():
                ctype = attach.get_content_type()
                file_name = attach.get_filename()

                if file_name is None:
                    # 根据内容类型猜测文件名
                    if ctype.startswith("image/"):
                        file_name = "image.png"
                    elif ctype == "application/pdf":
                        file_name = "attachment.pdf"
                    elif ctype in [
                        "application/msword",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ]:
                        file_name = "document.docx"
                    else:
                        file_name = "attachment.bin"
                else:
                    # 解码文件名
                    file_name = self._decode_header(file_name)

                attach_data = attach.get_payload(decode=True)

                if attach_data and ctype != "message/rfc822":
                    attach_content = ""

                    # 创建临时文件来处理附件内容
                    import os
                    import tempfile

                    try:
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=os.path.splitext(file_name)[1]
                        ) as temp_file:
                            temp_file.write(attach_data)
                            temp_file_path = temp_file.name

                        # 如果是文档类型，尝试提取文本内容
                        file_ext = os.path.splitext(file_name)[1].lower()
                        if file_ext in [".pdf", ".docx", ".txt", ".doc"]:
                            try:
                                # 这里可以集成其他解析器来提取附件内容
                                # 暂时只记录文件信息
                                attach_content = (
                                    f"附件文件: {file_name} (类型: {ctype})"
                                )
                            except Exception:
                                traceback.print_exc()
                                attach_content = ""

                        # 清理临时文件
                        try:
                            os.unlink(temp_file_path)
                        except Exception:
                            pass

                    except Exception:
                        traceback.print_exc()
                        attach_content = ""
                else:
                    attach_content = ""

                # 添加到文件列表
                attachment["files"].append(
                    {
                        "file_name": file_name,
                        "file_content": attach_content,
                        "attach_name": file_name,
                        "content_type": ctype,
                        "size": len(attach_data) if attach_data else 0,
                    }
                )

                # 如果是图片，添加到图片列表
                if ctype.startswith("image/"):
                    attachment["images"].append(
                        {
                            "file_name": file_name,
                            "content_type": ctype,
                            "size": len(attach_data) if attach_data else 0,
                        }
                    )

        except Exception as e:
            traceback.print_exc()
            print(f"附件解析错误: {e}")

        return attachment

    def _parse_attachment_content(
        self, payload: bytes, filename: str, content_type: str
    ) -> Dict[str, Any]:
        """
        解析附件内容，使用FileParserTool进行解析

        Args:
            payload: 附件二进制数据
            filename: 文件名
            content_type: 内容类型

        Returns:
            Dict[str, Any]: 解析结果，包含content字段
        """
        temp_file_path = None
        try:
            # 获取文件扩展名
            file_ext = os.path.splitext(filename)[1].lower() if filename else ""

            # 如果没有扩展名，根据content_type推断
            if not file_ext:
                if content_type.startswith("text/plain"):
                    file_ext = ".txt"
                elif content_type.startswith("text/html"):
                    file_ext = ".html"
                elif content_type == "application/pdf":
                    file_ext = ".pdf"
                elif content_type in [
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ]:
                    file_ext = ".docx"
                elif content_type in [
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ]:
                    file_ext = ".xlsx"
                elif content_type in [
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                ]:
                    file_ext = ".pptx"

            # 创建临时文件
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=file_ext
            ) as temp_file:
                temp_file.write(payload)
                temp_file_path = temp_file.name

            # 导入FileParserTool
            from ..file_parser import FileParser

            # 创建解析器实例
            parser_tool = FileParser()

            # 使用FileParserTool解析附件
            # 处理异步调用，避免事件循环冲突

            def run_async_in_thread():
                # 在新线程中创建新的事件循环
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        parser_tool.extract_text_from_file(
                            file_path_or_url=temp_file_path,
                            start_index=0,
                            enable_text_cleaning=True,
                        )
                    )
                finally:
                    new_loop.close()

            # 在线程池中执行异步操作
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async_in_thread)
                parse_result = future.result()

            if parse_result.get("success", False):
                return {
                    "content": parse_result.get("text", ""),
                    "content_type_parsed": "file_parser_tool",
                    "content_length": len(parse_result.get("text", "")),
                    "word_count": parse_result.get("text_info", {}).get("words", 0),
                    "file_extension": file_ext,
                    "original_filename": filename,
                    "parse_metadata": parse_result.get("metadata", {}),
                    "file_info": parse_result.get("file_info", {}),
                    "text_info": parse_result.get("text_info", {}),
                }
            else:
                # 如果FileParserTool解析失败，回退到简单的文本解析
                return self._fallback_text_parse(payload, content_type, filename)

        except Exception as e:
            print(f"使用FileParserTool解析附件内容时出错: {e}")
            traceback.print_exc()
            # 回退到简单的文本解析
            return self._fallback_text_parse(payload, content_type, filename)
        finally:
            # 清理临时文件
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    def _fallback_text_parse(
        self, payload: bytes, content_type: str, filename: str
    ) -> Dict[str, Any]:
        """
        回退的文本解析方法，当FileParserTool解析失败时使用

        Args:
            payload: 附件二进制数据
            content_type: 内容类型
            filename: 文件名

        Returns:
            Dict[str, Any]: 解析结果
        """
        try:
            # 尝试作为文本解析
            if content_type.startswith("text/") or any(
                filename.lower().endswith(ext)
                for ext in [".txt", ".md", ".csv", ".json", ".xml"]
            ):
                # 尝试不同编码解码文本
                text_content = None
                encoding_used = None

                for encoding in ["utf-8", "gbk", "gb2312", "latin1"]:
                    try:
                        text_content = payload.decode(encoding)
                        encoding_used = encoding
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue

                if text_content is None:
                    text_content = payload.decode("utf-8", errors="ignore")
                    encoding_used = "utf-8 (with errors ignored)"

                return {
                    "content": text_content,
                    "content_type_parsed": "fallback_text",
                    "encoding_used": encoding_used,
                    "content_length": len(text_content),
                    "word_count": len(text_content.split()) if text_content else 0,
                    "original_filename": filename,
                }
            else:
                # 非文本文件，返回基本信息
                return {
                    "content": f"[无法解析的{content_type}文件: {filename}]",
                    "content_type_parsed": "unsupported",
                    "original_filename": filename,
                    "content_type": content_type,
                    "payload_size": len(payload),
                }
        except Exception as e:
            return {
                "content_parse_error": f"回退解析失败: {str(e)}",
                "original_filename": filename,
                "content_type": content_type,
            }

    def _extract_metadata(self, msg: email.message.EmailMessage) -> dict:
        """
        提取邮件元数据，增强容错性和完整性
        """
        try:
            metadata = {}

            # 提取发件人（增强容错）
            sender = self._safe_get_header(msg, "From")
            if not sender:
                # 尝试其他可能的发件人字段
                sender = (
                    self._safe_get_header(msg, "Sender")
                    or self._safe_get_header(msg, "Return-Path")
                    or self._safe_get_header(msg, "Reply-To")
                )

            # 解析发件人地址
            if sender:
                try:
                    if self.flanker_available:
                        parsed = address.parse(sender)
                        if parsed:
                            metadata["sender"] = parsed.full_spec
                        else:
                            metadata["sender"] = sender
                    else:
                        # 使用我们的清理方法
                        _, clean_addr = self._parse_email_address(sender)
                        metadata["sender"] = clean_addr if clean_addr else sender
                except Exception as e:
                    print(f"发件人解析失败: {e}")
                    # 容错处理，清理地址
                    clean_sender = sender.replace("\r", "").replace("\n", " ").strip()
                    metadata["sender"] = clean_sender
            else:
                metadata["sender"] = ""

            # 提取收件人（增强容错）
            receiver = self._safe_get_header(msg, "To")
            if not receiver:
                # 尝试其他可能的收件人字段
                receiver = (
                    self._safe_get_header(msg, "Delivered-To")
                    or self._safe_get_header(msg, "X-Original-To")
                    or self._safe_get_header(msg, "X-Envelope-To")
                )

            # 解析收件人地址
            if receiver:
                try:
                    if self.flanker_available:
                        parsed = address.parse(receiver)
                        if parsed:
                            metadata["receiver"] = parsed.full_spec
                        else:
                            metadata["receiver"] = receiver
                    else:
                        # 使用我们的清理方法
                        _, clean_addr = self._parse_email_address(receiver)
                        metadata["receiver"] = clean_addr if clean_addr else receiver
                except Exception as e:
                    print(f"收件人解析失败: {e}")
                    # 容错处理，清理地址
                    clean_receiver = (
                        receiver.replace("\r", "").replace("\n", " ").strip()
                    )
                    metadata["receiver"] = clean_receiver
            else:
                metadata["receiver"] = ""

            # 提取抄送
            cc = self._safe_get_header(msg, "Cc")
            metadata["cc"] = cc if cc else ""

            # 提取主题（增强处理）
            subject = self._safe_get_header(msg, "Subject")
            if not subject or subject.strip() == "":
                # 如果主题为空，尝试从邮件体中提取
                subject = self._extract_subject_from_body(msg)
                if not subject:
                    # 尝试从其他字段获取主题信息
                    subject = (
                        self._safe_get_header(msg, "X-Subject")
                        or self._safe_get_header(msg, "Thread-Topic")
                        or ""
                    )

            # 解码主题
            if subject:
                try:
                    decoded_subject = email.header.decode_header(subject)
                    subject_parts = []
                    for part, encoding in decoded_subject:
                        if isinstance(part, bytes):
                            if encoding:
                                try:
                                    subject_parts.append(part.decode(encoding))
                                except (UnicodeDecodeError, LookupError):
                                    subject_parts.append(
                                        self._smart_decode(part, encoding)
                                    )
                            else:
                                subject_parts.append(self._smart_decode(part, None))
                        else:
                            subject_parts.append(str(part))
                    metadata["subject"] = "".join(subject_parts).strip()
                except Exception as e:
                    print(f"主题解码失败: {e}")
                    metadata["subject"] = subject
            else:
                metadata["subject"] = ""

            # 提取日期（增强处理）
            date = self._safe_get_header(msg, "Date")
            if not date:
                # 尝试其他日期字段
                date = (
                    self._safe_get_header(msg, "Received")
                    or self._safe_get_header(msg, "X-Date")
                    or self._safe_get_header(msg, "Delivery-Date")
                )

                # 如果是Received字段，提取其中的日期
                if date and date.startswith("from"):
                    import re

                    date_match = re.search(r";\s*(.+)$", date)
                    if date_match:
                        date = date_match.group(1).strip()

            metadata["date"] = date if date else ""

            # 提取消息ID
            message_id = self._safe_get_header(msg, "Message-ID")
            if not message_id:
                # 尝试其他ID字段
                message_id = self._safe_get_header(
                    msg, "Message-Id"
                ) or self._safe_get_header(msg, "X-Message-ID")
            metadata["message_id"] = message_id if message_id else ""

            # 提取邮件体
            body = self._extract_body(msg)
            metadata["body"] = body

            # 提取附件
            attachments = self._extract_attachments(msg)
            metadata["attachments"] = attachments

            return metadata

        except Exception as e:
            print(f"元数据提取失败: {e}")
            import traceback

            traceback.print_exc()
            return {
                "sender": "",
                "receiver": "",
                "cc": "",
                "subject": "",
                "date": "",
                "message_id": "",
                "body": "",
                "attachments": [],
            }

    def _html2txt(self, html_content):
        """
        HTML转文本，增强容错性和清理功能
        """
        if not html_content or not html_content.strip():
            return ""

        try:
            # 尝试使用BeautifulSoup
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html_content, "html.parser")

                # 移除script和style标签
                for script in soup(["script", "style"]):
                    script.decompose()

                # 获取文本内容
                text = soup.get_text(separator="\n", strip=True)

                # 清理文本
                import re

                # 移除过多的空行
                text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
                # 移除行首行尾空格
                lines = [line.strip() for line in text.split("\n")]
                text = "\n".join(line for line in lines if line)

                return text

            except ImportError:
                # 如果没有BeautifulSoup，使用html2text
                h = html2text.HTML2Text()
                h.ignore_links = True
                h.ignore_images = True
                h.ignore_emphasis = True
                h.body_width = 0  # 不限制行宽
                text = h.handle(html_content)

                # 清理html2text的输出
                import re

                text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
                text = text.strip()

                return text

        except Exception as e:
            print(f"HTML转文本失败: {e}")
            # 最后的备选方案：简单的标签移除
            import re

            text = re.sub(r"<[^>]+>", "", html_content)
            text = re.sub(r"&[a-zA-Z0-9#]+;", " ", text)  # 移除HTML实体
            text = re.sub(r"\s+", " ", text)  # 合并空白字符
            return text.strip()

    def _clean_body_text_placeholder(self, body_text: str):
        """
        清理邮件正文中的占位符和无用内容
        """
        if not body_text:
            return ""

        import re

        # 先转换HTML（如果包含HTML标签）
        if "<" in body_text and ">" in body_text:
            body_text = self._html2txt(body_text)

        # 移除邮件相关的占位符
        body_text = re.sub(r"<mailto:.*?>", "", body_text)
        body_text = re.sub(r"\[cid:.*?\]", "", body_text)
        body_text = re.sub(r"\bmage.*?", "", body_text)

        # 移除分隔线
        body_text = re.sub(r"=[=~]+(?![=~])", "", body_text)
        body_text = re.sub(r"---{3,}", "", body_text)
        body_text = re.sub(r"___{3,}", "", body_text)
        body_text = re.sub(r"====={3,}", "", body_text)

        # 移除过多的空行
        body_text = re.sub(r"\n\s*\n\s*\n", "\n\n", body_text)

        # 移除行首行尾空格
        lines = [line.strip() for line in body_text.split("\n")]
        body_text = "\n".join(lines)

        return body_text.strip()
