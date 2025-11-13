import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Host
import uvicorn
from typing import List, Dict, Any, Union, Optional, Tuple
import argparse
import json
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

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("File System")

parser = argparse.ArgumentParser(description="启动文件系统 MCP Server")
args = parser.parse_args()


class FileSystemError(Exception):
    """文件系统异常"""

    pass


class SecurityValidator:
    """安全验证器"""

    # 危险的文件扩展名
    DANGEROUS_EXTENSIONS = {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".pif",
        ".scr",
        ".vbs",
        ".js",
        ".jar",
        ".app",
        ".deb",
        ".pkg",
        ".rpm",
        ".dmg",
        ".iso",
    }

    # 系统关键目录（禁止操作）
    PROTECTED_PATHS = {
        "/System",
        "/usr/bin",
        "/usr/sbin",
        "/bin",
        "/sbin",
        "/Windows/System32",
        "/Windows/SysWOW64",
        "/Program Files",
        "/Program Files (x86)",
    }

    @staticmethod
    def validate_path(file_path: str, allow_dangerous: bool = False) -> Dict[str, Any]:
        """验证文件路径的安全性"""
        try:
            # 检查路径遍历攻击（在解析前检查）
            if ".." in file_path:
                return {"valid": False, "error": "路径包含危险的遍历字符"}

            path = Path(file_path).resolve()

            # 检查是否为绝对路径
            if not path.is_absolute():
                return {"valid": False, "error": "必须提供绝对路径"}

            # 检查系统保护目录
            path_str = str(path)
            for protected in SecurityValidator.PROTECTED_PATHS:
                if path_str.startswith(protected):
                    return {
                        "valid": False,
                        "error": f"禁止访问系统保护目录: {protected}",
                    }

            # 检查危险文件扩展名
            if (
                not allow_dangerous
                and path.suffix.lower() in SecurityValidator.DANGEROUS_EXTENSIONS
            ):
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
                info.update(
                    {
                        "extension": path.suffix.lower(),
                        "mime_type": mimetypes.guess_type(str(path))[0] or "unknown",
                        "encoding": (
                            FileMetadata._detect_encoding(file_path)
                            if path.suffix.lower()
                            in [".txt", ".py", ".js", ".css", ".html", ".md"]
                            else None
                        ),
                    }
                )

            # 权限信息
            info["permissions"] = {
                "readable": os.access(file_path, os.R_OK),
                "writable": os.access(file_path, os.W_OK),
                "executable": os.access(file_path, os.X_OK),
                "mode": (
                    oct(stat_info.st_mode)[-3:]
                    if platform.system() != "Windows"
                    else None
                ),
            }

            return info

        except Exception as e:
            return {"exists": False, "error": str(e)}

    @staticmethod
    def _detect_encoding(file_path: str) -> str:
        """检测文件编码"""
        try:
            with open(file_path, "rb") as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                return result.get("encoding", "utf-8")
        except Exception:
            return "utf-8"


class CloudStorage:
    """云存储管理器"""

    DEFAULT_UPLOAD_URL = "http://36.133.44.114:20034/askonce/api/v1/doc/upload"
    DEFAULT_HEADERS = {"User-Source": "AskOnce_bakend"}

    @staticmethod
    async def upload_file(
        file_path: str, upload_url: str = None, headers: Dict = None
    ) -> Dict[str, Any]:
        """上传文件到云存储"""
        start_time = time.time()
        operation_id = hashlib.md5(
            f"upload_{file_path}_{time.time()}".encode()
        ).hexdigest()[:8]
        logger.info(
            f"☁️ CloudStorage.upload_file开始执行 [{operation_id}] - 文件: {file_path}"
        )

        try:
            if not os.path.exists(file_path):
                error_time = time.time() - start_time
                logger.error(
                    f"❌ 文件不存在 [{operation_id}] - 文件: {file_path}, 耗时: {error_time:.2f}秒"
                )
                return {"status": "error", "message": "文件不存在"}

            # 检查文件大小（限制100MB）
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            logger.info(f"📊 文件信息 [{operation_id}] - 大小: {file_size_mb:.2f}MB")

            if file_size > 100 * 1024 * 1024:
                error_time = time.time() - start_time
                logger.error(
                    f"❌ 文件过大 [{operation_id}] - 大小: {file_size_mb:.2f}MB > 100MB, 耗时: {error_time:.2f}秒"
                )
                return {"status": "error", "message": "文件过大，超过100MB限制"}

            file_name = os.path.basename(file_path)
            url = upload_url or CloudStorage.DEFAULT_UPLOAD_URL
            request_headers = headers or CloudStorage.DEFAULT_HEADERS

            logger.debug(f"🔗 上传配置 [{operation_id}] - URL: {url}")
            logger.debug(f"📋 请求头 [{operation_id}] - Headers: {request_headers}")
            logger.info(f"📁 准备上传文件 [{operation_id}] - 文件名: {file_name}")

            # 发起上传请求
            upload_start_time = time.time()
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, "application/octet-stream")}
                logger.info(f"🌐 开始上传请求 [{operation_id}]")

                response = requests.post(
                    url, headers=request_headers, files=files, timeout=60
                )

            upload_time = time.time() - upload_start_time
            logger.info(
                f"⏱️ 上传请求完成 [{operation_id}] - 状态码: {response.status_code}, 上传耗时: {upload_time:.2f}秒"
            )

            response.raise_for_status()

            try:
                json_data = response.json()
                logger.debug(f"📄 API响应内容 [{operation_id}] - {json_data}")

                # 获取文件URL - 直接获取，类似原代码逻辑
                file_url = json_data.get("data", {}).get("url")
                file_id = json_data.get("data", {}).get("fileId")

                if not file_url:
                    error_time = time.time() - start_time
                    logger.error(
                        f"❌ API响应中缺少URL [{operation_id}] - 完整响应: {json_data}, 耗时: {error_time:.2f}秒"
                    )
                    return {
                        "status": "error",
                        "message": "API返回成功但缺少文件URL",
                        "response": json_data,
                    }

                total_time = time.time() - start_time
                logger.info(
                    f"✅ 文件上传成功 [{operation_id}] - URL: {file_url}, 文件ID: {file_id}, 总耗时: {total_time:.2f}秒"
                )

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
                    "operation_id": operation_id,
                }

            except json.JSONDecodeError as e:
                error_time = time.time() - start_time
                logger.error(
                    f"❌ JSON解析失败 [{operation_id}] - 错误: {str(e)}, 响应: {response.text[:500]}, 耗时: {error_time:.2f}秒"
                )
                return {
                    "status": "error",
                    "message": "服务器响应格式错误",
                    "response": response.text,
                }

        except requests.exceptions.Timeout:
            error_time = time.time() - start_time
            logger.error(f"⏰ 上传超时 [{operation_id}] - 耗时: {error_time:.2f}秒")
            return {"status": "error", "message": "上传超时"}
        except requests.exceptions.RequestException as e:
            error_time = time.time() - start_time
            logger.error(
                f"💥 网络请求失败 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": f"网络请求失败: {str(e)}"}
        except Exception as e:
            error_time = time.time() - start_time
            logger.error(
                f"💥 上传异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
            )
            logger.error(f"🔍 异常详情: {traceback.format_exc()}")
            return {"status": "error", "message": f"上传失败: {str(e)}"}


# ==================== MCP 工具函数 ====================


@mcp.tool()
async def file_read(
    file_path: str,
    start_line: int = 0,
    end_line: Optional[int] = None,
    encoding: str = "auto",
    max_size_mb: float = 10.0,
) -> Dict[str, Any]:
    """高级文件读取工具

    Args:
        file_path (str): 文件绝对路径
        start_line (int): 开始行号，默认0
        end_line (Optional[int]): 结束行号（不包含），None表示读取到末尾
        encoding (str): 文件编码，'auto'表示自动检测
        max_size_mb (float): 最大读取文件大小（MB），默认10MB

    Returns:
        Dict: 包含文件内容和元信息
    """
    start_time = time.time()
    operation_id = hashlib.md5(f"read_{file_path}_{time.time()}".encode()).hexdigest()[
        :8
    ]
    logger.info(f"📖 file_read开始执行 [{operation_id}] - 文件: {file_path}")
    logger.info(
        f"🔧 参数: start_line={start_line}, end_line={end_line}, encoding={encoding}, max_size_mb={max_size_mb}"
    )

    try:
        # 安全验证
        logger.debug(f"🔒 开始安全验证 [{operation_id}]")
        validation = SecurityValidator.validate_path(file_path)
        if not validation["valid"]:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 安全验证失败 [{operation_id}] - 错误: {validation['error']}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": validation["error"]}

        file_path = validation["resolved_path"]
        logger.info(f"✅ 安全验证通过 [{operation_id}] - 解析路径: {file_path}")

        # 获取文件信息
        logger.debug(f"📊 获取文件信息 [{operation_id}]")
        file_info = FileMetadata.get_file_info(file_path)
        if not file_info["exists"]:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 文件不存在 [{operation_id}] - 路径: {file_path}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": "文件不存在"}

        if not file_info["is_file"]:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 不是文件 [{operation_id}] - 路径: {file_path}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": "指定路径不是文件"}

        if not file_info["permissions"]["readable"]:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 文件不可读 [{operation_id}] - 路径: {file_path}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": "文件无读取权限"}

        # 检查文件大小
        if file_info["size_mb"] > max_size_mb:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 文件过大 [{operation_id}] - 大小: {file_info['size_mb']:.2f}MB > {max_size_mb}MB, 耗时: {error_time:.2f}秒"
            )
            return {
                "status": "error",
                "message": f"文件过大: {file_info['size_mb']:.2f}MB > {max_size_mb}MB",
            }

        logger.info(
            f"📊 文件信息 [{operation_id}] - 大小: {file_info['size_mb']:.2f}MB, 权限: 可读"
        )

        # 检测编码
        if encoding == "auto":
            encoding = file_info.get("encoding", "utf-8")
            logger.debug(f"🔤 自动检测编码 [{operation_id}] - 编码: {encoding}")

        # 读取文件内容
        read_start_time = time.time()
        logger.info(f"📖 开始读取文件内容 [{operation_id}]")

        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        read_time = time.time() - read_start_time

        # 处理行范围
        total_lines = len(lines)
        if end_line is None:
            end_line = total_lines

        start_line = max(0, start_line)
        end_line = min(total_lines, end_line)

        if start_line >= total_lines:
            content = ""
        else:
            content = "".join(lines[start_line:end_line])

        total_time = time.time() - start_time

        logger.info(
            f"✅ 文件读取成功 [{operation_id}] - 总行数: {total_lines}, 读取行数: {end_line - start_line}, 内容长度: {len(content)}, 读取耗时: {read_time:.2f}秒, 总耗时: {total_time:.2f}秒"
        )

        return {
            "status": "success",
            "message": f"成功读取文件 (行 {start_line}-{end_line})",
            "content": content,
            "file_info": {
                "path": file_path,
                "total_lines": total_lines,
                "read_lines": end_line - start_line,
                "encoding": encoding,
                "size_mb": file_info["size_mb"],
            },
            "line_range": {"start": start_line, "end": end_line, "total": total_lines},
            "execution_time": total_time,
            "operation_id": operation_id,
        }

    except UnicodeDecodeError as e:
        error_time = time.time() - start_time
        logger.error(
            f"❌ 编码错误 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        return {
            "status": "error",
            "message": f"文件编码错误: {str(e)}，请尝试指定正确的编码",
        }
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(
            f"💥 读取文件异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        return {"status": "error", "message": f"读取文件失败: {str(e)}"}


@mcp.tool()
async def file_write(
    file_path: str,
    content: str,
    mode: str = "overwrite",
    encoding: str = "utf-8",
    auto_upload: bool = True,
) -> Dict[str, Any]:
    """智能文件写入工具

    Args:
        file_path (str): 文件绝对路径
        content (str): 要写入的内容
        mode (str): 写入模式 - 'overwrite', 'append', 'prepend'
        encoding (str): 文件编码，默认utf-8
        auto_upload (bool): 是否自动上传到云端，默认True

    Returns:
        Dict: 操作结果和文件信息
    """
    start_time = time.time()
    operation_id = hashlib.md5(f"write_{file_path}_{time.time()}".encode()).hexdigest()[
        :8
    ]
    logger.info(f"✏️ file_write开始执行 [{operation_id}] - 文件: {file_path}")
    logger.info(
        f"🔧 参数: mode={mode}, encoding={encoding}, auto_upload={auto_upload}, 内容长度: {len(content)}"
    )

    try:
        # 安全验证
        logger.debug(f"🔒 开始安全验证 [{operation_id}]")
        validation = SecurityValidator.validate_path(file_path)
        if not validation["valid"]:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 安全验证失败 [{operation_id}] - 错误: {validation['error']}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": validation["error"]}

        file_path = validation["resolved_path"]
        path = Path(file_path)
        logger.info(f"✅ 安全验证通过 [{operation_id}] - 解析路径: {file_path}")

        # 创建目录结构
        if not path.parent.exists():
            logger.info(f"📁 创建目录结构 [{operation_id}] - 目录: {path.parent}")
            path.parent.mkdir(parents=True, exist_ok=True)

        # 处理写入模式
        logger.debug(f"📝 处理写入模式 [{operation_id}] - 模式: {mode}")
        if mode == "overwrite":
            write_mode = "w"
            final_content = content
        elif mode == "append":
            write_mode = "a"
            final_content = content
        elif mode == "prepend":
            write_mode = "w"
            if path.exists():
                logger.debug(f"📖 读取现有内容用于prepend [{operation_id}]")
                with open(file_path, "r", encoding=encoding) as f:
                    existing_content = f.read()
                final_content = content + existing_content
                logger.debug(
                    f"📝 合并内容 [{operation_id}] - 新内容长度: {len(content)}, 原内容长度: {len(existing_content)}, 最终长度: {len(final_content)}"
                )
            else:
                final_content = content
        else:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 不支持的写入模式 [{operation_id}] - 模式: {mode}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": f"不支持的写入模式: {mode}"}

        # 写入文件
        write_start_time = time.time()
        logger.info(
            f"✏️ 开始写入文件 [{operation_id}] - 最终内容长度: {len(final_content)}"
        )

        with open(file_path, write_mode, encoding=encoding) as f:
            f.write(final_content)

        write_time = time.time() - write_start_time
        logger.info(f"✅ 文件写入完成 [{operation_id}] - 写入耗时: {write_time:.2f}秒")

        # 获取文件信息
        file_info = FileMetadata.get_file_info(file_path)
        logger.debug(
            f"📊 文件信息 [{operation_id}] - 大小: {file_info['size_mb']:.2f}MB"
        )

        result = {
            "status": "success",
            "message": f"文件写入成功 ({mode}模式)",
            "file_info": {
                "path": file_path,
                "size_mb": file_info["size_mb"],
                "encoding": encoding,
            },
            "operation": {
                "mode": mode,
                "content_length": len(content),
                "final_content_length": len(final_content),
                "write_time": write_time,
                "timestamp": datetime.now().isoformat(),
            },
            "operation_id": operation_id,
        }

        # 自动上传到云端
        if auto_upload:
            logger.info(f"☁️ 开始自动上传到云端 [{operation_id}]")
            try:
                upload_result = await update_file_to_cloud_drive(file_path)
                if upload_result["status"] == "success":
                    result["cloud_url"] = upload_result["url"]
                    result["file_id"] = upload_result.get("file_id")
                    result["message"] += "，已上传到云端"
                    logger.info(
                        f"✅ 云端上传成功 [{operation_id}] - URL: {upload_result['url']}"
                    )
                else:
                    result["upload_error"] = upload_result["message"]
                    logger.warning(
                        f"⚠️ 云端上传失败 [{operation_id}] - 错误: {upload_result['message']}"
                    )
            except Exception as e:
                result["upload_error"] = f"云端上传失败: {str(e)}"
                logger.error(f"💥 云端上传异常 [{operation_id}] - 错误: {str(e)}")
                logger.error(f"🔍 异常详情: {traceback.format_exc()}")

        total_time = time.time() - start_time
        result["execution_time"] = total_time

        logger.info(
            f"✅ file_write执行完成 [{operation_id}] - 总耗时: {total_time:.2f}秒"
        )

        return result

    except Exception as e:
        error_time = time.time() - start_time
        logger.error(
            f"💥 文件写入异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"文件写入失败: {str(e)}",
            "operation_id": operation_id,
        }


@mcp.tool()
async def update_file_to_cloud_drive(file_path: str) -> dict:
    """Upload a file to a cloud drive. It is useful for uploading files to cloud drive for later use. For example, show files in markdown format.

    Args:
        file_path (str): The path of the file to upload.

    Returns:
        dict: Status message and file url
    """
    start_time = time.time()
    operation_id = hashlib.md5(
        f"upload_cloud_drive_{file_path}_{time.time()}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"☁️ update_file_to_cloud_drive开始执行 [{operation_id}] - 文件: {file_path}"
    )

    try:
        # 检查文件是否存在
        logger.debug(f"📂 检查文件存在性 [{operation_id}] - 路径: {file_path}")
        if not os.path.exists(file_path):
            error_time = time.time() - start_time
            logger.error(
                f"❌ 文件不存在 [{operation_id}] - 路径: {file_path}, 耗时: {error_time:.2f}秒"
            )
            return {"status": "error", "message": "File not found."}

        # 获取文件名
        file_name = os.path.basename(file_path)
        logger.info(f"📝 文件名: {file_name} [{operation_id}]")
        print(f"[DEBUG] File name: {file_name}")

        # 获取文件大小
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        logger.info(f"📊 文件大小: {file_size_mb:.2f}MB [{operation_id}]")

        # 设置上传URL和headers
        url = "http://36.133.44.114:20034/askonce/api/v1/doc/upload"
        headers = {"User-Source": "AskOnce_bakend"}
        logger.debug(f"🔗 上传URL: {url} [{operation_id}]")
        logger.debug(f"📋 请求头: {headers} [{operation_id}]")

        payload = {}

        # 准备文件上传
        logger.info(f"📤 准备上传文件 [{operation_id}] - 开始打开文件")
        with open(file_path, "rb") as file_obj:
            files = {"file": (file_name, file_obj, "application/octet-stream")}
            logger.debug(f"📋 文件参数准备完成 [{operation_id}]")

            # 发起HTTP请求
            upload_start_time = time.time()
            logger.info(f"🌐 发起POST请求 [{operation_id}] - 开始上传")
            response = requests.request(
                "POST", url, headers=headers, data=payload, files=files, timeout=60
            )
            upload_time = time.time() - upload_start_time

            logger.info(
                f"📡 请求完成 [{operation_id}] - 状态码: {response.status_code}, 上传耗时: {upload_time:.2f}秒"
            )
            print(f"[DEBUG] Response status: {response.status_code}")
            print(f"[DEBUG] Response headers: {dict(response.headers)}")

        # 处理响应
        logger.debug(
            f"📄 处理响应内容 [{operation_id}] - 响应长度: {len(response.text)}"
        )
        try:
            json_data = json.loads(response.text)
            logger.info(f"✅ JSON解析成功 [{operation_id}]")
            logger.debug(f"📄 响应内容: {json_data} [{operation_id}]")
            print(f"[DEBUG] JSON response: {json_data}")

            # 检查响应中是否有URL
            if "data" in json_data and "url" in json_data["data"]:
                file_url = json_data["data"]["url"]
                total_time = time.time() - start_time
                logger.info(
                    f"🎉 文件上传成功 [{operation_id}] - URL: {file_url}, 总耗时: {total_time:.2f}秒"
                )
                return {
                    "status": "success",
                    "message": "Successfully uploaded to cloud drive",
                    "url": file_url,
                    "file_name": file_name,
                    "file_size_mb": file_size_mb,
                    "upload_time": upload_time,
                    "total_time": total_time,
                    "operation_id": operation_id,
                }
            else:
                error_time = time.time() - start_time
                logger.error(
                    f"❌ 响应中缺少URL [{operation_id}] - 响应: {json_data}, 耗时: {error_time:.2f}秒"
                )
                return {
                    "status": "error",
                    "message": "Response missing file URL",
                    "response": json_data,
                }

        except json.JSONDecodeError as e:
            error_time = time.time() - start_time
            logger.error(
                f"❌ JSON解析失败 [{operation_id}] - 错误: {str(e)}, 响应: {response.text[:500]}, 耗时: {error_time:.2f}秒"
            )
            print(f"[DEBUG] JSON decode error: {str(e)}")
            print(f"[DEBUG] Raw response: {response.text}")
            return {
                "status": "error",
                "message": "Failed to decode JSON response.",
                "response": response.text,
            }

    except requests.exceptions.Timeout:
        error_time = time.time() - start_time
        logger.error(f"⏰ 请求超时 [{operation_id}] - 耗时: {error_time:.2f}秒")
        return {"status": "error", "message": "Upload request timed out"}
    except requests.exceptions.RequestException as e:
        error_time = time.time() - start_time
        logger.error(
            f"💥 网络请求异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        print(f"[DEBUG] Request exception: {str(e)}")
        return {"status": "error", "message": f"Network request failed: {str(e)}"}
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(
            f"💥 上传异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        print(f"[DEBUG] Unexpected error: {str(e)}")
        return {
            "status": "error",
            "message": f"An error occurred: {str(e)}",
            "operation_id": operation_id,
        }


@mcp.tool()
async def save_file_from_url(url: str, working_dir: str) -> str:
    """Download a file from a given URL and save it to the specified working directory.

    Args:
        url (str): The URL of the file to download.
        working_dir (str): The current working directory to save the file.

    Returns:
        str: The path of the downloaded file.
    """
    start_time = time.time()
    operation_id = hashlib.md5(f"download_{url}_{time.time()}".encode()).hexdigest()[:8]
    logger.info(f"📥 save_file_from_url开始执行 [{operation_id}] - URL: {url}")
    logger.info(f"🔧 参数: working_dir={working_dir}")

    try:
        # 检查工作目录是否存在
        logger.debug(f"📂 检查工作目录 [{operation_id}] - 目录: {working_dir}")
        if not os.path.exists(working_dir):
            error_time = time.time() - start_time
            logger.error(
                f"❌ 工作目录不存在 [{operation_id}] - 目录: {working_dir}, 耗时: {error_time:.2f}秒"
            )
            print(f"[DEBUG] Working directory {working_dir} does not exist.")
            return f"Working directory {working_dir} does not exist."

        logger.info(f"✅ 工作目录存在 [{operation_id}] - 目录: {working_dir}")

        # 发起HTTP请求下载文件
        download_start_time = time.time()
        logger.info(f"🌐 开始下载文件 [{operation_id}] - URL: {url}")
        print(f"[DEBUG] Starting download from: {url}")

        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        download_time = time.time() - download_start_time

        # 获取文件大小
        content_length = len(response.content)
        content_size_mb = content_length / (1024 * 1024)
        logger.info(
            f"📊 下载完成 [{operation_id}] - 大小: {content_size_mb:.2f}MB, 下载耗时: {download_time:.2f}秒"
        )
        print(f"[DEBUG] Downloaded {content_size_mb:.2f}MB in {download_time:.2f}s")

        # 解码URL并获取文件名
        decoded_url = urllib.parse.unquote(url)
        logger.debug(f"🔤 URL解码 [{operation_id}] - 原始: {url}")
        logger.debug(f"🔤 URL解码 [{operation_id}] - 解码后: {decoded_url}")
        print(f"[DEBUG] Decoded URL: {decoded_url}")

        file_name = os.path.basename(decoded_url)
        # 如果文件名为空或者只是路径分隔符，使用默认名称
        if not file_name or file_name in ["/", "\\"]:
            file_name = f"downloaded_file_{operation_id}"
            logger.warning(
                f"⚠️ 无法从URL获取文件名，使用默认名称 [{operation_id}] - 文件名: {file_name}"
            )

        logger.info(f"📝 文件名: {file_name} [{operation_id}]")
        print(f"[DEBUG] File name: {file_name}")

        # 构建完整文件路径
        file_path = os.path.join(working_dir, file_name)
        logger.debug(f"📍 文件保存路径 [{operation_id}] - 路径: {file_path}")
        print(f"[DEBUG] File path: {file_path}")

        # 检查文件是否已存在，如果存在则添加后缀
        original_file_path = file_path
        counter = 1
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_file_path)
            file_path = f"{name}_{counter}{ext}"
            counter += 1
            logger.debug(
                f"🔄 文件已存在，尝试新路径 [{operation_id}] - 路径: {file_path}"
            )

        # 保存文件
        save_start_time = time.time()
        logger.info(f"💾 开始保存文件 [{operation_id}] - 路径: {file_path}")
        with open(file_path, "wb") as f:
            f.write(response.content)
        save_time = time.time() - save_start_time

        # 验证文件是否保存成功
        if os.path.exists(file_path):
            saved_size = os.path.getsize(file_path)
            logger.info(
                f"✅ 文件保存成功 [{operation_id}] - 路径: {file_path}, 保存大小: {saved_size}, 保存耗时: {save_time:.2f}秒"
            )
            if saved_size != content_length:
                logger.warning(
                    f"⚠️ 文件大小不匹配 [{operation_id}] - 下载: {content_length}, 保存: {saved_size}"
                )
        else:
            error_time = time.time() - start_time
            logger.error(
                f"❌ 文件保存失败 [{operation_id}] - 路径: {file_path}, 耗时: {error_time:.2f}秒"
            )
            return f"Failed to save file to {file_path}"

        total_time = time.time() - start_time
        success_message = f"文件保存成功，地址：{file_path}"
        logger.info(
            f"🎉 save_file_from_url执行完成 [{operation_id}] - 总耗时: {total_time:.2f}秒"
        )
        print(f"[DEBUG] {success_message}")
        return success_message

    except httpx.HTTPStatusError as e:
        error_time = time.time() - start_time
        error_msg = f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        logger.error(
            f"🌐 HTTP错误 [{operation_id}] - 状态码: {e.response.status_code}, 耗时: {error_time:.2f}秒"
        )
        logger.error(
            f"🌐 HTTP错误详情 [{operation_id}] - 响应: {e.response.text[:500]}"
        )
        print(f"[DEBUG] {error_msg}")
        return error_msg
    except httpx.RequestError as e:
        error_time = time.time() - start_time
        error_msg = f"Error communicating with the server: {str(e)}"
        logger.error(
            f"💥 网络通信错误 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        print(f"[DEBUG] Request error: {str(e)}")
        return error_msg
    except Exception as e:
        error_time = time.time() - start_time
        error_msg = f"An unexpected error occurred: {str(e)}"
        logger.error(
            f"💥 未预期错误 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒"
        )
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        print(f"[DEBUG] Unexpected error: {str(e)}")
        return error_msg


@mcp.tool()
async def file_operations(operation: str, **kwargs) -> Dict[str, Any]:
    """复杂文件操作工具（仅用于命令行无法处理的复杂场景）

    Args:
        operation (str): 操作类型 - 'search_replace', 'get_info', 'batch_process'
        **kwargs: 操作相关参数

    Returns:
        Dict: 操作结果
    """
    try:
        if operation == "search_replace":
            return await _search_replace(**kwargs)
        elif operation == "get_info":
            return await _get_file_info(**kwargs)
        elif operation == "batch_process":
            return await _batch_process(**kwargs)
        else:
            return {"status": "error", "message": f"不支持的操作类型: {operation}"}

    except Exception as e:
        return {"status": "error", "message": f"操作失败: {str(e)}"}


async def _search_replace(
    file_path: str,
    search_pattern: str,
    replacement: str,
    use_regex: bool = False,
    case_sensitive: bool = True,
) -> Dict[str, Any]:
    """搜索替换（仅用于复杂正则表达式场景）"""
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
        with open(file_path, "r", encoding=encoding) as f:
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
        with open(file_path, "w", encoding=encoding) as f:
            f.write(new_content)

        return {
            "status": "success",
            "message": f"成功替换 {replace_count} 处匹配项",
            "statistics": {
                "replacements": replace_count,
                "original_length": len(original_content),
                "new_length": len(new_content),
                "length_change": len(new_content) - len(original_content),
            },
        }

    except re.error as e:
        return {"status": "error", "message": f"正则表达式错误: {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"搜索替换失败: {str(e)}"}


async def _get_file_info(file_path: str) -> Dict[str, Any]:
    """获取文件详细信息（仅用于需要完整元数据的场景）"""
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
                info["checksums"] = {
                    "md5": hashlib.md5(open(file_path, "rb").read()).hexdigest(),
                    "sha256": hashlib.sha256(open(file_path, "rb").read()).hexdigest(),
                }
            except Exception as e:
                info["checksum_error"] = str(e)

        return {"status": "success", "message": "文件信息获取成功", "file_info": info}

    except Exception as e:
        return {"status": "error", "message": f"获取文件信息失败: {str(e)}"}


async def _batch_process(
    operation: str, file_paths: List[str], **params
) -> Dict[str, Any]:
    """批量处理文件（仅用于需要原子性的批量操作）"""
    try:
        results = []
        errors = []

        for file_path in file_paths:
            try:
                if operation == "compress":
                    # 创建压缩包
                    archive_path = params.get("archive_path")
                    archive_type = params.get("archive_type", "zip")

                    if archive_type == "zip":
                        with zipfile.ZipFile(
                            archive_path, "w", zipfile.ZIP_DEFLATED
                        ) as zipf:
                            for fp in file_paths:
                                if os.path.exists(fp):
                                    zipf.write(fp, os.path.basename(fp))

                    results.append({"file": file_path, "status": "success"})

            except Exception as e:
                errors.append({"file": file_path, "error": str(e)})

        return {
            "status": "success",
            "message": f"批量处理完成，成功: {len(results)}，失败: {len(errors)}",
            "results": results,
            "errors": errors,
        }

    except Exception as e:
        return {"status": "error", "message": f"批量处理失败: {str(e)}"}


if __name__ == "__main__":
    app = Starlette(
        routes=[
            Mount("/", app=mcp.sse_app()),
        ]
    )

    uvicorn.run(app, host="0.0.0.0", port=34100)
