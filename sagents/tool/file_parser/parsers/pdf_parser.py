"""
PDF文件解析器
支持PDF文件的文本提取和元数据获取
"""

import os
import traceback
from typing import Dict, Any
import pdfplumber
from .base_parser import BaseFileParser, ParseResult


class PDFParser(BaseFileParser):
    """PDF文件解析器"""
    
    SUPPORTED_EXTENSIONS = ['.pdf']
    SUPPORTED_MIME_TYPES = ['application/pdf']
    
    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析PDF文件
        
        Args:
            file_path: PDF文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）
            
        Returns:
            ParseResult: 解析结果
        """
        if not self.validate_file(file_path):
            return self.create_error_result(f"文件不存在或无法读取: {file_path}", file_path)
        
        if not skip_validation and not self.can_parse(file_path):
            return self.create_error_result(f"不支持的文件类型: {file_path}", file_path)
        
        try:
            text_parts = []
            metadata = {}
            
            with pdfplumber.open(file_path) as pdf:
                # 获取PDF基本信息
                metadata.update({
                    "file_type": "pdf",
                    "page_count": len(pdf.pages),
                    "file_size": os.path.getsize(file_path)
                })
                
                # 获取PDF元数据
                if pdf.metadata:
                    pdf_info = pdf.metadata
                    metadata.update({
                        "title": pdf_info.get('Title', ''),
                        "author": pdf_info.get('Author', ''),
                        "subject": pdf_info.get('Subject', ''),
                        "creator": pdf_info.get('Creator', ''),
                        "producer": pdf_info.get('Producer', ''),
                        "creation_date": str(pdf_info.get('CreationDate', '')),
                        "modification_date": str(pdf_info.get('ModDate', ''))
                    })
                
                # 提取每页文本
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_parts.append(f"=== 第 {page_num} 页 ===\n{page_text}")
                        
                        # 获取页面尺寸信息
                        if page_num == 1:  # 只获取第一页的尺寸作为代表
                            metadata.update({
                                "page_width": page.width,
                                "page_height": page.height
                            })
                    except Exception as e:
                        print(f"提取第 {page_num} 页文本时出错: {e}")
                        traceback.print_exc()
                        text_parts.append(f"=== 第 {page_num} 页 ===\n[页面解析失败: {str(e)}]")
            
            # 合并所有文本
            full_text = '\n\n'.join(text_parts)
            
            # 添加文本统计信息
            metadata.update(self._get_text_stats(full_text))
            
            return ParseResult(
                text=full_text,
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            error_msg = f"PDF解析失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return ParseResult(
                text="",
                metadata={"file_type": "pdf", "error": error_msg},
                success=False,
                error=error_msg
            )
    
    def _extract_pdf_metadata(self, pdf_reader) -> Dict[str, Any]:
        """
        提取PDF特定的元数据
        
        Args:
            pdf_reader: PDF阅读器对象
            
        Returns:
            Dict[str, Any]: PDF元数据
        """
        metadata = {}
        
        try:
            # 基本信息
            metadata["page_count"] = len(pdf_reader.pages)
            metadata["is_encrypted"] = pdf_reader.is_encrypted
            
            # PDF文档信息
            if pdf_reader.metadata:
                doc_info = pdf_reader.metadata
                metadata.update({
                    "title": doc_info.get('/Title', ''),
                    "author": doc_info.get('/Author', ''),
                    "subject": doc_info.get('/Subject', ''),
                    "creator": doc_info.get('/Creator', ''),
                    "producer": doc_info.get('/Producer', ''),
                    "creation_date": str(doc_info.get('/CreationDate', '')),
                    "modification_date": str(doc_info.get('/ModDate', '')),
                    "keywords": doc_info.get('/Keywords', '')
                })
            
            # 页面信息
            if pdf_reader.pages:
                first_page = pdf_reader.pages[0]
                if hasattr(first_page, 'mediabox'):
                    mediabox = first_page.mediabox
                    metadata.update({
                        "page_width": float(mediabox.width),
                        "page_height": float(mediabox.height),
                        "page_size": f"{float(mediabox.width)} x {float(mediabox.height)}"
                    })
            
        except Exception as e:
            print(f"提取PDF元数据时出错: {e}")
            traceback.print_exc()
            metadata["metadata_extraction_error"] = str(e)
        
        return metadata