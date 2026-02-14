import os
import hashlib
import mimetypes
import time
from datetime import datetime
from pathlib import Path
import platform
from typing import Dict, Any, Optional
import asyncio

from sagents.utils.logger import logger


class SecurityValidator:

    DANGEROUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.com', '.pif', '.scr', '.vbs', '.js',
        '.jar', '.app', '.deb', '.pkg', '.rpm', '.dmg', '.iso'
    }

    PROTECTED_PATHS = {
        '/System', '/usr/bin', '/usr/sbin', '/bin', '/sbin',
        '/Windows/System32', '/Windows/SysWOW64', '/Program Files',
        '/Program Files (x86)'
    }

    @staticmethod
    def validate_path(file_path: str, allow_dangerous: bool = False) -> Dict[str, Any]:
        try:
            if '..' in file_path:
                return {"valid": False, "error": "路径包含危险的遍历字符"}

            path = Path(file_path).resolve()

            if not path.is_absolute():
                return {"valid": False, "error": "必须提供绝对路径"}

            path_str = str(path)
            for protected in SecurityValidator.PROTECTED_PATHS:
                if path_str.startswith(protected):
                    return {"valid": False, "error": f"禁止访问系统保护目录: {protected}"}

            if not allow_dangerous and path.suffix.lower() in SecurityValidator.DANGEROUS_EXTENSIONS:
                return {"valid": False, "error": f"危险的文件类型: {path.suffix}"}

            return {"valid": True, "resolved_path": str(path)}

        except Exception as e:
            return {"valid": False, "error": f"路径验证失败: {str(e)}"}


class FileMetadata:

    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        try:
            path = Path(file_path)

            if not path.exists():
                return {"exists": False}

            stat_info = path.stat()

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

            if path.is_file():
                info.update({
                    "extension": path.suffix.lower(),
                    "mime_type": mimetypes.guess_type(str(path))[0] or "unknown",
                    "encoding": FileMetadata._detect_encoding(file_path) if path.suffix.lower() in ['.txt', '.py', '.js', '.css', '.html', '.md'] else None
                })

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
        try:
            try:
                import chardet
            except Exception:
                return 'utf-8'
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                return result.get('encoding') or 'utf-8'
        except Exception:
            return 'utf-8'


async def file_read_core(file_path: str, start_line: int = 0, end_line: Optional[int] = 20,
                         encoding: str = "auto", max_size_mb: float = 10.0) -> Dict[str, Any]:
    start_time = time.time()
    operation_id = hashlib.md5(f"read_{file_path}_{time.time()}".encode()).hexdigest()[:8]
    logger.info(f"📖 file_read开始执行 [{operation_id}] - 文件: {file_path}")

    try:
        validation = SecurityValidator.validate_path(file_path)
        if not validation["valid"]:
            return {"status": "error", "message": validation["error"]}

        file_path = validation["resolved_path"]

        file_info = await asyncio.to_thread(FileMetadata.get_file_info, file_path)
        if not file_info["exists"]:
            return {"status": "error", "message": "文件不存在"}

        if not file_info["is_file"]:
            return {"status": "error", "message": "指定路径不是文件"}

        if not file_info["permissions"]["readable"]:
            return {"status": "error", "message": "文件无读取权限"}

        if file_info["size_mb"] > max_size_mb:
            return {"status": "error", "message": f"文件过大: {file_info['size_mb']:.2f}MB > {max_size_mb}MB"}

        if encoding == "auto":
            encoding = file_info.get("encoding", "utf-8")

        def skill_read_file_lines():
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                return f.readlines()

        lines = await asyncio.to_thread(skill_read_file_lines)

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
