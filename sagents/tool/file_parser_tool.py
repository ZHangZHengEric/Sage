import os
import time
import hashlib
import asyncio
import concurrent.futures
from typing import Dict, Any, List, Optional

from .tool_base import ToolBase
from sagents.utils.logger import logger
from sagents.utils.file_parser import FileParser

class FileParserTool(ToolBase):
    """文件解析工具集"""

    def __init__(self):
        logger.debug("Initializing FileParserTool")
        super().__init__()

    @ToolBase.tool(
        description_i18n={
            "zh": "从非文本文件中提取Markdown文本（含PDF/Office/CSV等）",
            "en": "Extract Markdown text from non-text files (PDF/Office/CSV)",
            "pt": "Extrai texto Markdown de arquivos não textuais (PDF/Office/CSV)"
        },
        param_description_i18n={
            "input_file_path": {"zh": "输入文件的绝对路径", "en": "Absolute path of input file", "pt": "Caminho absoluto do arquivo de entrada"},
            "start_index": {"zh": "开始字符位置，默认0", "en": "Start character index, default 0", "pt": "Índice inicial de caractere, padrão 0"},
            "max_length": {"zh": "最大提取长度，默认5000，最大5000", "en": "Max extract length, default 5000, max 5000", "pt": "Comprimento máximo de extração, padrão 5000, máximo 5000"},
            "include_metadata": {"zh": "是否包含文件元数据", "en": "Whether to include file metadata", "pt": "Se deve incluir metadados do arquivo"}
        }
    )
    def extract_text_from_non_text_file(
        self, 
        input_file_path: str, 
        start_index: int = 0, 
        max_length: int = 500000,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """读取本地存储下的非文本文件，例如pdf，docx，doc，ppt，pptx，xlsx，xls，csv等文件，返回Markdown的文本数据

        Args:
            input_file_path (str): 输入文件路径，本地的绝对路径
            start_index (int): 开始提取的字符位置，默认0
            max_length (int): 单次最大提取长度，默认5000字符，最大5000字符
            include_metadata (bool): 是否包含文件元数据，默认True

        Returns:
            Dict[str, Any]: 包含提取文本和相关信息的字典
        """
        if max_length > 500000:
            max_length = 500000
        start_time = time.time()
        operation_id = hashlib.md5(f"extract_{input_file_path}_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"📄 extract_text_from_file开始执行 [{operation_id}] - 文件: {input_file_path}")
        logger.info(f"🔧 参数: start_index={start_index}, max_length={max_length}, include_metadata={include_metadata}")

        try:
            # 使用 Core Utils 中的 FileParser
            parser = FileParser()

            # FileParser.extract_text_from_file 返回的格式:
            # {
            #     "text": "...",
            #     "metadata": {...},
            #     "success": True,
            #     "error": None
            # }
            # 或者错误时:
            # {
            #     "success": False,
            #     "error": "..."
            # }

            def run_async_in_thread():
                # 在新线程中创建新的事件循环
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        parser.extract_text_from_file(
                            input_file_path,
                            start_index=start_index,
                            max_length=max_length,
                            timeout=120, # 稍微给多点时间处理大文件
                            enable_text_cleaning=True
                        )
                    )
                finally:
                    new_loop.close()

            # 在线程池中执行异步操作
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async_in_thread)
                result = future.result()

            if not result.get("success"):
                error_time = time.time() - start_time
                error_msg = result.get("error", "未知错误")
                logger.error(f"❌ 文件解析失败 [{operation_id}] - 错误: {error_msg}, 耗时: {error_time:.2f}秒")
                return {
                    "success": False,
                    "error": error_msg,
                    "file_path": input_file_path,
                    "execution_time": error_time,
                    "operation_id": operation_id
                }

            # 成功
            extracted_text = result.get("text", "")
            metadata = result.get("metadata", {})

            # 过滤掉不需要的元数据，如果 include_metadata 为 False
            if not include_metadata:
                metadata = {}

            execution_time = time.time() - start_time
            logger.info(f"✅ 文件解析成功 [{operation_id}] - 原始文本长度: {len(extracted_text)}, 解析耗时: {execution_time:.2f}秒")

            return {
                "success": True,
                "text": extracted_text,
                "metadata": metadata,
                "file_path": input_file_path,
                "execution_time": execution_time,
                "operation_id": operation_id
            }

        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"❌ 系统异常 [{operation_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
            return {
                "success": False,
                "error": f"系统异常: {str(e)}",
                "file_path": input_file_path,
                "execution_time": error_time,
                "operation_id": operation_id
            }
