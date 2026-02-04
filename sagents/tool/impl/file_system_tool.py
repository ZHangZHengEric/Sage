import os
import hashlib
import time
from datetime import datetime
from pathlib import Path
import urllib.parse
import re
from typing import Dict, Any, Optional, List
import asyncio

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.file_system_utils import SecurityValidator, FileMetadata, file_read_core
class FileSystemError(Exception):
    """文件系统异常"""
    pass

class FileSystemTool:
    """文件系统操作工具集"""
  
    @tool(
        description_i18n={
            "zh": "读取文本文件指定行范围内容",
            "en": "Read text file within a line range",
            "pt": "Lê conteúdo do arquivo em intervalo de linhas"
        },
        param_description_i18n={
            "file_path": {"zh": "文件绝对路径", "en": "Absolute file path", "pt": "Caminho absoluto do arquivo"},
            "start_line": {"zh": "开始行号，默认0", "en": "Start line number, default 0", "pt": "Linha inicial, padrão 0"},
            "end_line": {"zh": "结束行号（不包含），默认200，None表示读取到文件末尾", "en": "End line number (exclusive), default 200, None means read to end", "pt": "Linha final (exclusiva), padrão 200, None significa ler até o final"},
            "encoding": {"zh": "文件编码，auto自动检测", "en": "File encoding, 'auto' for detection", "pt": "Codificação, 'auto' para detectar"},
            "max_size_mb": {"zh": "最大读取文件大小（MB）", "en": "Maximum file size to read (MB)", "pt": "Tamanho máximo do arquivo para leitura (MB)"}
        }
    )
    async def file_read(self, file_path: str, start_line: int = 0, end_line: Optional[int] = 200, 
                  encoding: str = "auto", max_size_mb: float = 10.0) -> Dict[str, Any]:
        """高级文件读取工具，读取文本文件，例如txt，以及配置文件和代码文件

        Args:
            file_path (str): 文件绝对路径
            start_line (int): 开始行号，默认0
            end_line (int): 结束行号（不包含），默认200，None表示读取到文件末尾
            encoding (str): 文件编码，'auto'表示自动检测
            max_size_mb (float): 最大读取文件大小（MB），默认10MB

        Returns:
            Dict[str, Any]: 包含文件内容和元信息
        """
        
        return await file_read_core(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            encoding=encoding,
            max_size_mb=max_size_mb
        )

    @tool(
        description_i18n={
            "zh": "按模式写入文本到文件",
            "en": "Write text to file with mode",
            "pt": "Grava texto no arquivo com modo"
        },
        param_description_i18n={
            "file_path": {"zh": "文件绝对路径", "en": "Absolute file path", "pt": "Caminho absoluto do arquivo"},
            "content": {"zh": "要写入的文本内容", "en": "Text content to write", "pt": "Conteúdo de texto a gravar"},
            "mode": {"zh": "写入模式 overwrite/append/prepend", "en": "Write mode overwrite/append/prepend", "pt": "Modo de gravação overwrite/append/prepend"},
            "encoding": {"zh": "文件编码", "en": "File encoding", "pt": "Codificação do arquivo"}
        }
    )
    async def file_write(self, file_path: str, content: str, mode: str = "overwrite", 
                   encoding: str = "utf-8") -> Dict[str, Any]:
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
                    def read_existing():
                        with open(file_path, 'r', encoding=encoding) as f:
                            return f.read()
                    existing_content = await asyncio.to_thread(read_existing)
                    final_content = content + existing_content
                else:
                    final_content = content
            else:
                return {"status": "error", "message": f"不支持的写入模式: {mode}"}
            
            # 写入文件
            write_start_time = time.time()
            
            def write_file():
                with open(file_path, write_mode, encoding=encoding) as f:
                    f.write(final_content)
            
            await asyncio.to_thread(write_file)
            
            write_time = time.time() - write_start_time
            
            # 获取文件信息
            file_info = await asyncio.to_thread(FileMetadata.get_file_info, file_path)
            
            result: Dict[str, Any] = {
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
            # if auto_upload:
            #     try:
            #         upload_result = self.upload_file_to_cloud(file_path)
            #         if upload_result["status"] == "success":
            #             result["cloud_url"] = upload_result["url"]
            #             result["file_id"] = upload_result.get("file_id")
            #             result["message"] += "，已上传到云端"
            #         else:
            #             result["upload_error"] = upload_result["message"]
            #     except Exception as e:
            #         result["upload_error"] = f"云端上传失败: {str(e)}"
            
            total_time = time.time() - start_time
            result["execution_time"] = total_time
            
            return result
            
        except Exception as e:
            logger.error(f"💥 文件写入异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"文件写入失败: {str(e)}", "operation_id": operation_id}

    @tool(
        description_i18n={
            "zh": "按关键词检索文件并返回上下文",
            "en": "Search file by keywords and return context",
            "pt": "Pesquisa por palavras-chave e retorna contexto"
        },
        param_description_i18n={
            "file_path": {"zh": "要搜索的文件路径", "en": "File path to search", "pt": "Caminho do arquivo para buscar"},
            "keywords": {"zh": "关键词列表", "en": "List of keywords", "pt": "Lista de palavras-chave"},
            "return_search_item": {"zh": "返回的匹配条目数量", "en": "Number of matched items to return", "pt": "Quantidade de resultados retornados"}
        }
    )
    def search_content_in_file(self, file_path: str, keywords:list[str],return_search_item=5) -> Dict[str, Any]:
        
        """在文件中通过关键词匹配，搜索相关的内容的上下文内容
        Args:
            file_path (str): 要搜索的文件路径
            keywords (list[str]): 要搜索的关键词列表
            return_search_item (int, optional): 返回的搜索结果数量，默认5个. Defaults to 5.
        Returns:
            Dict[str, Any]: 搜索结果，包含匹配的内容和上下文
        """
        context_size = 800
        return_search_item = int(return_search_item)
        start_time = time.time()
        operation_id = hashlib.md5(f"search_file_{file_path}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"🔍 search_content_in_file开始执行 [{operation_id}] - 文件: {file_path}")
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return {"status": "error", "message": "文件不存在"}
            
            # 读取文件的全部内容
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()

            # 存储搜索结果
            search_results = []
            file_content_lower = file_content.lower()
            
            # 找到所有关键词的匹配位置
            keyword_positions = {}
            for keyword in keywords:
                keyword_lower = keyword.lower()
                positions = []
                start = 0
                while True:
                    pos = file_content_lower.find(keyword_lower, start)
                    if pos == -1:
                        break
                    positions.append(pos)
                    start = pos + 1
                keyword_positions[keyword] = positions
            
            # 收集所有匹配位置并计算上下文
            all_positions = []
            for keyword, positions in keyword_positions.items():
                for pos in positions:
                    all_positions.append((pos, keyword))
            
            # 按位置排序
            all_positions.sort()
            
            # 合并相近的匹配位置，避免重复的上下文
            merged_results: List[Dict[str, Any]] = []
            for pos, keyword in all_positions:
                # 计算上下文范围
                start_char = max(0, pos - context_size // 2)
                end_char = min(len(file_content), pos + context_size // 2)
                
                # 检查是否与已有结果重叠
                overlapped = False
                for existing in merged_results:
                    if (start_char < existing['end_char'] and end_char > existing['start_char']):
                        # 合并重叠区域
                        existing['start_char'] = min(existing['start_char'], start_char)
                        existing['end_char'] = max(existing['end_char'], end_char)
                        if keyword not in existing['matched_keywords']:
                            existing['matched_keywords'].append(keyword)
                            existing['score'] += 1
                        overlapped = True
                        break
                
                if not overlapped:
                    # 提取上下文内容
                    context = file_content[start_char:end_char]
                    merged_results.append({
                        'score': 1,
                        'matched_keywords': [keyword],
                        'context': context.strip(),
                        'start_char': start_char,
                        'end_char': end_char,
                        'match_position': pos
                    })
            
            # 按分数降序排序，分数相同时按匹配位置升序
            merged_results.sort(key=lambda x: (-x['score'], x['match_position']))
            
            # 限制返回结果数量
            search_results = merged_results[:return_search_item]
            
            execution_time = time.time() - start_time
            logger.info(f"✅ search_content_in_file执行完成 [{operation_id}] - 耗时: {execution_time:.2f}s, 找到 {len(search_results)} 个匹配项")
            
            return {
                "status": "success",
                "message": f"搜索完成，找到 {len(search_results)} 个匹配项",
                "results": search_results,
                "total_matches": len(search_results),
                "keywords": keywords,
                "execution_time": execution_time,
                "operation_id": operation_id
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"搜索文件内容时发生错误: {str(e)}"
            logger.error(f"❌ search_content_in_file执行失败 [{operation_id}] - {error_msg} - 耗时: {execution_time:.2f}s")
            return {
                "status": "error",
                "message": error_msg,
                "execution_time": execution_time,
                "operation_id": operation_id
            }

    
    @tool(
        description_i18n={
            "zh": "从URL下载文件到目录",
            "en": "Download file from URL to directory",
            "pt": "Baixa arquivo da URL para diretório"
        },
        param_description_i18n={
            "url": {"zh": "要下载的文件URL", "en": "File URL to download", "pt": "URL do arquivo para download"},
            "working_dir": {"zh": "保存文件的目录", "en": "Directory to save the file", "pt": "Diretório para salvar o arquivo"}
        }
    )
    async def download_file_from_url(self, url: str, working_dir: str) -> Dict[str, Any]:
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
            try:
                import httpx
            except Exception as e:
                return {"status": "error", "message": f"httpx不可用: {str(e)}"}
            # 检查工作目录是否存在
            if not os.path.exists(working_dir):
                return {"status": "error", "message": f"工作目录不存在: {working_dir}"}
            
            # 发起HTTP请求下载文件
            download_start_time = time.time()
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
            
            download_time = time.time() - download_start_time
            
            # 获取文件大小
            content_length = len(content)
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
            await asyncio.to_thread(lambda: open(file_path, 'wb').write(content))
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
            
        except httpx.HTTPStatusError as e:
            return {"status": "error", "message": f"HTTP错误: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"status": "error", "message": f"网络请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"💥 下载异常 [{operation_id}] - 错误: {str(e)}")
            return {"status": "error", "message": f"下载失败: {str(e)}"}

    @tool(
        description_i18n={
            "zh": "在文件中搜索并替换文本",
            "en": "Search and replace text in file",
            "pt": "Busca e substitui texto no arquivo"
        },
        param_description_i18n={
            "file_path": {"zh": "文件绝对路径", "en": "Absolute file path", "pt": "Caminho absoluto do arquivo"},
            "search_pattern": {"zh": "要搜索的模式或文本", "en": "Pattern or text to search", "pt": "Padrão ou texto a buscar"},
            "replacement": {"zh": "替换文本", "en": "Replacement text", "pt": "Texto de substituição"},
            "use_regex": {"zh": "是否使用正则表达式", "en": "Use regular expression", "pt": "Usar expressão regular"},
            "case_sensitive": {"zh": "是否区分大小写", "en": "Case sensitive", "pt": "Diferenciar maiúsculas/minúsculas"}
        }
    )
    def update_file(self, file_path: str, search_pattern: str, replacement: str, 
                          use_regex: bool = False, case_sensitive: bool = True) -> Dict[str, Any]:
        """更新文件中匹配的文本内容

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
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
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
            with open(file_path, 'w', encoding=encoding, errors='ignore') as f:
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
    
    @tool(
        description_i18n={
            "zh": "将CSV转换为Excel",
            "en": "Convert CSV to Excel",
            "pt": "Converte CSV para Excel"
        },
        param_description_i18n={
            "csv_file_path": {"zh": "输入CSV文件路径", "en": "Input CSV file path", "pt": "Caminho do arquivo CSV de entrada"},
            "excel_file_path": {"zh": "输出Excel文件路径", "en": "Output Excel file path", "pt": "Caminho do arquivo Excel de saída"}
        }
    )
    def convert_csv_to_excel(self, csv_file_path: str, excel_file_path: str) -> Dict[str, Any]:
        """将CSV文件转换为Excel文件

        Args:
            csv_file_path (str): 输入的CSV文件路径
            excel_file_path (str): 输出的Excel文件路径

        Returns:
            Dict[str, Any]: 转换结果
        """
        
        # 检查文件是否存在
        if not os.path.exists(csv_file_path):
            return {"status": "error", "message": "输入的CSV文件不存在"}
        
        # 读取CSV文件
        import pandas as pd
        df = pd.read_csv(csv_file_path)
        
        # 写入Excel文件
        df.to_excel(excel_file_path, index=False)
        
        return {
            "status": "success",
            "message": "CSV文件已成功转换为Excel文件",
            "excel_file_path": excel_file_path
        }
