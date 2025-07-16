import os
import shutil
import tempfile
import hashlib
import mimetypes
import logging
import time
from datetime import datetime
from pathlib import Path
import urllib.parse
import requests
import asyncio
import stat
import platform
import zipfile
import tarfile
import re
import chardet
import traceback
from typing import Dict, Any, List, Optional, Union

from .tool_base import ToolBase
from sagents.utils.logger import logger

class FileSystemError(Exception):
    """文件系统异常"""
    pass

class SecurityValidator:
    """安全验证器"""
    
    # 危险的文件扩展名
    DANGEROUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.com', '.pif', '.scr', '.vbs', '.js',
        '.jar', '.app', '.deb', '.pkg', '.rpm', '.dmg', '.iso'
    }
    
    # 系统关键目录（禁止操作）
    PROTECTED_PATHS = {
        '/System', '/usr/bin', '/usr/sbin', '/bin', '/sbin',
        '/Windows/System32', '/Windows/SysWOW64', '/Program Files',
        '/Program Files (x86)'
    }
    
    @staticmethod
    def validate_path(file_path: str, allow_dangerous: bool = False) -> Dict[str, Any]:
        """验证文件路径的安全性"""
        try:
            # 检查路径遍历攻击（在解析前检查）
            if '..' in file_path:
                return {"valid": False, "error": "路径包含危险的遍历字符"}
            
            path = Path(file_path).resolve()
            
            # 检查是否为绝对路径
            if not path.is_absolute():
                return {"valid": False, "error": "必须提供绝对路径"}
            
            # 检查系统保护目录
            path_str = str(path)
            for protected in SecurityValidator.PROTECTED_PATHS:
                if path_str.startswith(protected):
                    return {"valid": False, "error": f"禁止访问系统保护目录: {protected}"}
            
            # 检查危险文件扩展名
            if not allow_dangerous and path.suffix.lower() in SecurityValidator.DANGEROUS_EXTENSIONS:
                return {"valid": False, "error": f"危险的文件类型: {path.suffix}"}
            
            return {"valid": True, "resolved_path": str(path)}
            
        except Exception as e:
            return {"valid": False, "error": f"路径验证失败: {str(e)}"}

class FileMetadata:
    """文件元数据管理器"""
    
    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        """获取文件详细信息"""
        try:
            path = Path(file_path)
            
            if not path.exists():
                return {"exists": False}
            
            stat_info = path.stat()
            
            # 基础信息
            info = {
                "exists": True,
                "name": path.name,
                "absolute_path": str(path.absolute()),
                "size_bytes": stat_info.st_size,
                "size_mb": round(stat_info.st_size / (1024 * 1024), 2),
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
                "is_symlink": path.is_symlink(),
                "created_time": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
                "modified_time": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "accessed_time": datetime.fromtimestamp(stat_info.st_atime).isoformat(),
            }
            
            # 文件特定信息
            if path.is_file():
                info.update({
                    "extension": path.suffix.lower(),
                    "mime_type": mimetypes.guess_type(str(path))[0] or "unknown",
                    "encoding": FileMetadata._detect_encoding(file_path) if path.suffix.lower() in ['.txt', '.py', '.js', '.css', '.html', '.md'] else None
                })
            
            # 权限信息
            info["permissions"] = {
                "readable": os.access(file_path, os.R_OK),
                "writable": os.access(file_path, os.W_OK),
                "executable": os.access(file_path, os.X_OK),
                "mode": oct(stat_info.st_mode)[-3:] if platform.system() != 'Windows' else None
            }
            
            return info
            
        except Exception as e:
            return {"exists": False, "error": str(e)}
    
    @staticmethod
    def _detect_encoding(file_path: str) -> str:
        """检测文件编码"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                return result.get('encoding', 'utf-8')
        except Exception:
            return 'utf-8'

class FileSystemTool(ToolBase):
    """文件系统操作工具集"""
    
    def __init__(self):
        logger.debug("Initializing FileSystemTool")
        super().__init__()
        self.default_upload_url = "http://36.133.44.114:20034/askonce/api/v1/doc/upload"
        self.default_headers = {"User-Source": 'AskOnce_bakend'}

    @ToolBase.tool()
    def file_read(self, file_path: str, start_line: int = 0, end_line: Optional[int] = None, 
                  encoding: str = "auto", max_size_mb: float = 10.0) -> Dict[str, Any]:
        """高级文件读取工具

        Args:
            file_path (str): 文件绝对路径
            start_line (int): 开始行号，默认0
            end_line (int): 结束行号（不包含），None表示读取到末尾
            encoding (str): 文件编码，'auto'表示自动检测
            max_size_mb (float): 最大读取文件大小（MB），默认10MB

        Returns:
            Dict[str, Any]: 包含文件内容和元信息
        """
        start_time = time.time()
        operation_id = hashlib.md5(f"read_{file_path}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"📖 file_read开始执行 [{operation_id}] - 文件: {file_path}")
        
        try:
            # 安全验证
            validation = SecurityValidator.validate_path(file_path)
            if not validation["valid"]:
                return {"status": "error", "message": validation["error"]}
            
            file_path = validation["resolved_path"]
            
            # 获取文件信息
            file_info = FileMetadata.get_file_info(file_path)
            if not file_info["exists"]:
                return {"status": "error", "message": "文件不存在"}
            
            if not file_info["is_file"]:
                return {"status": "error", "message": "指定路径不是文件"}
            
            if not file_info["permissions"]["readable"]:
                return {"status": "error", "message": "文件无读取权限"}
            
            # 检查文件大小
            if file_info["size_mb"] > max_size_mb:
                return {"status": "error", "message": f"文件过大: {file_info['size_mb']:.2f}MB > {max_size_mb}MB"}
            
            # 检测编码
            if encoding == "auto":
                encoding = file_info.get("encoding", "utf-8")
            
            # 读取文件内容
            with open(file_path, 'r', encoding=encoding) as f:
                lines = f.readlines()
            
            # 处理行范围
            total_lines = len(lines)
            if end_line is None:
                end_line = total_lines
            
            start_line = max(0, start_line)
            end_line = min(total_lines, end_line)
            
            if start_line >= total_lines:
                content = ""
            else:
                content = ''.join(lines[start_line:end_line])
            
            total_time = time.time() - start_time
            
            return {
                "status": "success",
                "message": f"成功读取文件 (行 {start_line}-{end_line})",
                "content": content,
                "file_info": {
                    "path": file_path,
                    "total_lines": total_lines,
                    "read_lines": end_line - start_line,
                    "encoding": encoding,
                    "size_mb": file_info["size_mb"]
                },
                "line_range": {
                    "start": start_line,
                    "end": end_line,
                    "total": total_lines
                },
                "execution_time": total_time,
                "operation_id": operation_id
            }
            
        except UnicodeDecodeError as e:
            return {"status": "error", "message": f"文件编码错误: {str(e)}，请尝试指定正确的编码"}
        except Exception as e:
            logger.error(f"💥 读取文件异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"读取文件失败: {str(e)}"}

    @ToolBase.tool()
    def file_write(self, file_path: str, content: str, mode: str = "overwrite", 
                   encoding: str = "utf-8", auto_upload: bool = True) -> Dict[str, Any]:
        """智能文件写入工具

        Args:
            file_path (str): 文件绝对路径
            content (str): 要写入的内容
            mode (str): 写入模式 - 'overwrite', 'append', 'prepend'
            encoding (str): 文件编码，默认utf-8
            auto_upload (bool): 是否自动上传到云端，默认True
            
        Returns:
            Dict[str, Any]: 操作结果和文件信息
        """
        start_time = time.time()
        operation_id = hashlib.md5(f"write_{file_path}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"✏️ file_write开始执行 [{operation_id}] - 文件: {file_path}")
        
        try:
            # 安全验证
            validation = SecurityValidator.validate_path(file_path)
            if not validation["valid"]:
                return {"status": "error", "message": validation["error"]}
            
            file_path = validation["resolved_path"]
            path = Path(file_path)
            
            # 创建目录结构
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            
            # 处理写入模式
            if mode == "overwrite":
                write_mode = 'w'
                final_content = content
            elif mode == "append":
                write_mode = 'a'
                final_content = content
            elif mode == "prepend":
                write_mode = 'w'
                if path.exists():
                    with open(file_path, 'r', encoding=encoding) as f:
                        existing_content = f.read()
                    final_content = content + existing_content
                else:
                    final_content = content
            else:
                return {"status": "error", "message": f"不支持的写入模式: {mode}"}
            
            # 写入文件
            write_start_time = time.time()
            with open(file_path, write_mode, encoding=encoding) as f:
                f.write(final_content)
            write_time = time.time() - write_start_time
            
            # 获取文件信息
            file_info = FileMetadata.get_file_info(file_path)
            
            result = {
                "status": "success",
                "message": f"文件写入成功 ({mode}模式)",
                "file_info": {
                    "path": file_path,
                    "size_mb": file_info["size_mb"],
                    "encoding": encoding
                },
                "operation": {
                    "mode": mode,
                    "content_length": len(content),
                    "final_content_length": len(final_content),
                    "write_time": write_time,
                    "timestamp": datetime.now().isoformat()
                },
                "operation_id": operation_id
            }
            
            # 自动上传到云端
            if auto_upload:
                try:
                    upload_result = self.upload_file_to_cloud(file_path)
                    if upload_result["status"] == "success":
                        result["cloud_url"] = upload_result["url"]
                        result["file_id"] = upload_result.get("file_id")
                        result["message"] += "，已上传到云端"
                    else:
                        result["upload_error"] = upload_result["message"]
                except Exception as e:
                    result["upload_error"] = f"云端上传失败: {str(e)}"
            
            total_time = time.time() - start_time
            result["execution_time"] = total_time
            
            return result
            
        except Exception as e:
            logger.error(f"💥 文件写入异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"文件写入失败: {str(e)}", "operation_id": operation_id}

    @ToolBase.tool()
    def upload_file_to_cloud(self, file_path: str) -> Dict[str, Any]:
        """上传文件到云端存储
        
        Args:
            file_path (str): 要上传的文件路径
            
        Returns:
            Dict[str, Any]: 上传结果，包含状态和文件URL
        """
        start_time = time.time()
        operation_id = hashlib.md5(f"upload_cloud_{file_path}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"☁️ upload_file_to_cloud开始执行 [{operation_id}] - 文件: {file_path}")
        
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return {"status": "error", "message": "文件不存在"}
            
            # 获取文件信息
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            
            # 检查文件大小（限制100MB）
            if file_size > 100 * 1024 * 1024:
                return {"status": "error", "message": "文件过大，超过100MB限制"}
            
            # 准备上传
            url = self.default_upload_url
            headers = self.default_headers
            
            # 发起上传请求
            upload_start_time = time.time()
            with open(file_path, 'rb') as f:
                files = {'file': (file_name, f, 'application/octet-stream')}
                response = requests.post(url, headers=headers, files=files, timeout=60)
            
            upload_time = time.time() - upload_start_time
            response.raise_for_status()
            
            # 处理响应
            json_data = response.json()
            file_url = json_data.get('data', {}).get('url')
            file_id = json_data.get('data', {}).get('fileId')
            
            if not file_url:
                return {
                    "status": "error", 
                    "message": "API返回成功但缺少文件URL",
                    "response": json_data
                }
            
            total_time = time.time() - start_time
            
            return {
                "status": "success", 
                "message": "文件上传成功", 
                "url": file_url,
                "file_id": file_id,
                "file_name": file_name,
                "file_size": file_size,
                "file_size_mb": file_size_mb,
                "upload_time": upload_time,
                "total_time": total_time,
                "operation_id": operation_id
            }
                
        except requests.exceptions.Timeout:
            return {"status": "error", "message": "上传超时"}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"网络请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"💥 上传异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"上传失败: {str(e)}"}

    @ToolBase.tool()
    def download_file_from_url(self, url: str, working_dir: str) -> Dict[str, Any]:
        """从URL下载文件并保存到指定目录

        Args:
            url (str): 要下载的文件URL
            working_dir (str): 保存文件的工作目录

        Returns:
            Dict[str, Any]: 下载结果，包含保存的文件路径
        """
        start_time = time.time()
        operation_id = hashlib.md5(f"download_{url}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"📥 download_file_from_url开始执行 [{operation_id}] - URL: {url}")
        
        try:
            # 检查工作目录是否存在
            if not os.path.exists(working_dir):
                return {"status": "error", "message": f"工作目录不存在: {working_dir}"}
            
            # 发起HTTP请求下载文件
            download_start_time = time.time()
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            download_time = time.time() - download_start_time
            
            # 获取文件大小
            content_length = len(response.content)
            content_size_mb = content_length / (1024 * 1024)
            
            # 解码URL并获取文件名
            decoded_url = urllib.parse.unquote(url)
            file_name = os.path.basename(decoded_url)
            
            # 如果文件名为空，使用默认名称
            if not file_name or file_name in ['/', '\\']:
                file_name = f"downloaded_file_{operation_id}"
            
            # 构建完整文件路径
            file_path = os.path.join(working_dir, file_name)
            
            # 检查文件是否已存在，如果存在则添加后缀
            original_file_path = file_path
            counter = 1
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_file_path)
                file_path = f"{name}_{counter}{ext}"
                counter += 1
            
            # 保存文件
            save_start_time = time.time()
            with open(file_path, 'wb') as f:
                f.write(response.content)
            save_time = time.time() - save_start_time
            
            # 验证文件是否保存成功
            if not os.path.exists(file_path):
                return {"status": "error", "message": f"文件保存失败: {file_path}"}
            
            saved_size = os.path.getsize(file_path)
            if saved_size != content_length:
                logger.warning(f"⚠️ 文件大小不匹配 [{operation_id}] - 下载: {content_length}, 保存: {saved_size}")
            
            total_time = time.time() - start_time
            
            return {
                "status": "success",
                "message": "文件下载成功",
                "file_path": file_path,
                "file_name": file_name,
                "file_size": saved_size,
                "file_size_mb": content_size_mb,
                "download_time": download_time,
                "save_time": save_time,
                "total_time": total_time,
                "operation_id": operation_id
            }
            
        except requests.exceptions.HTTPError as e:
            return {"status": "error", "message": f"HTTP错误: {e.response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"网络请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"💥 下载异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"下载失败: {str(e)}"}

    @ToolBase.tool()
    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """获取文件详细信息

        Args:
            file_path (str): 文件或目录的绝对路径

        Returns:
            Dict[str, Any]: 文件详细信息
        """
        try:
            # 安全验证
            validation = SecurityValidator.validate_path(file_path)
            if not validation["valid"]:
                return {"status": "error", "message": validation["error"]}
            
            file_path = validation["resolved_path"]
            
            # 获取基础信息
            info = FileMetadata.get_file_info(file_path)
            if not info["exists"]:
                return {"status": "error", "message": "文件或目录不存在"}
            
            # 为小文件添加校验和
            if info["is_file"] and info["size_mb"] < 10:
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    info["checksums"] = {
                        "md5": hashlib.md5(content).hexdigest(),
                        "sha256": hashlib.sha256(content).hexdigest()
                    }
                except Exception as e:
                    info["checksum_error"] = str(e)
            
            return {
                "status": "success",
                "message": "文件信息获取成功",
                "file_info": info
            }
            
        except Exception as e:
            return {"status": "error", "message": f"获取文件信息失败: {str(e)}"}

    @ToolBase.tool()
    def search_and_replace(self, file_path: str, search_pattern: str, replacement: str, 
                          use_regex: bool = False, case_sensitive: bool = True) -> Dict[str, Any]:
        """在文件中搜索并替换文本

        Args:
            file_path (str): 文件绝对路径
            search_pattern (str): 要搜索的模式
            replacement (str): 替换文本
            use_regex (bool): 是否使用正则表达式
            case_sensitive (bool): 是否区分大小写

        Returns:
            Dict[str, Any]: 替换结果统计
        """
        try:
            # 安全验证
            validation = SecurityValidator.validate_path(file_path)
            if not validation["valid"]:
                return {"status": "error", "message": validation["error"]}
            
            file_path = validation["resolved_path"]
            
            # 检查文件
            file_info = FileMetadata.get_file_info(file_path)
            if not file_info["exists"] or not file_info["is_file"]:
                return {"status": "error", "message": "文件不存在或不是有效文件"}
            
            # 读取文件
            encoding = file_info.get("encoding", "utf-8")
            with open(file_path, 'r', encoding=encoding) as f:
                original_content = f.read()
            
            # 执行搜索替换
            if use_regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(search_pattern, flags)
                new_content, replace_count = pattern.subn(replacement, original_content)
            else:
                if case_sensitive:
                    new_content = original_content.replace(search_pattern, replacement)
                    replace_count = original_content.count(search_pattern)
                else:
                    pattern = re.compile(re.escape(search_pattern), re.IGNORECASE)
                    new_content, replace_count = pattern.subn(replacement, original_content)
            
            # 写入修改后的内容
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(new_content)
            
            return {
                "status": "success",
                "message": f"成功替换 {replace_count} 处匹配项",
                "statistics": {
                    "replacements": replace_count,
                    "original_length": len(original_content),
                    "new_length": len(new_content),
                    "length_change": len(new_content) - len(original_content)
                }
            }
            
        except re.error as e:
            return {"status": "error", "message": f"正则表达式错误: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"搜索替换失败: {str(e)}"} 