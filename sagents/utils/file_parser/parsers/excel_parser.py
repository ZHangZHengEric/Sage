"""
Excel文件解析器
支持Excel文件(.xlsx, .xls)的文本提取和元数据获取
"""

import traceback
import os
import subprocess
from typing import Dict, Any, List
import pandas as pd
import openpyxl
from .base_parser import BaseFileParser, ParseResult
from sagents.utils.logger import logger


class ExcelParser(BaseFileParser):
    """Excel文件解析器"""
    
    SUPPORTED_EXTENSIONS = ['.xlsx', '.xls']
    SUPPORTED_MIME_TYPES = [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ]
    
    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析Excel文件
        
        Args:
            file_path: Excel文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）
            
        Returns:
            ParseResult: 解析结果
        """
        if not self.validate_file(file_path):
            return self.create_error_result(f"文件不存在或无法读取: {file_path}", file_path)
        
        if not skip_validation and not self.can_parse(file_path):
            return self.create_error_result(f"不支持的文件类型: {file_path}", file_path)
        
        temp_xlsx_path = None
        
        try:
            # 检查文件扩展名
            ext = os.path.splitext(file_path)[1].lower()
            target_path = file_path
            
            # 如果是XLS文件，尝试转换为XLSX
            if ext == '.xls':
                try:
                    # 优先尝试转换，以保持与FileParserTool一致的能力
                    temp_xlsx_path = self._convert_xls_to_xlsx(file_path)
                    target_path = temp_xlsx_path
                except Exception as e:
                    logger.warning(f"XLS转换失败: {str(e)}，尝试直接读取")
                    target_path = file_path

            # 读取Excel文件
            excel_file = pd.ExcelFile(target_path)
            
            # 提取所有工作表的文本内容
            text_parts = []
            sheet_data = []
            
            for sheet_name in excel_file.sheet_names:
                try:
                    # 首先尝试正常读取（第一行作为列标题）
                    df = pd.read_excel(target_path, sheet_name=sheet_name)
                    
                    # 如果DataFrame为空，尝试不使用header读取
                    if df.empty:
                        df_no_header = pd.read_excel(target_path, sheet_name=sheet_name, header=None)
                        if not df_no_header.empty:
                            # 如果不使用header能读到数据，说明只有标题行
                            df = df_no_header
                            has_header_only = True
                        else:
                            has_header_only = False
                    else:
                        has_header_only = False
                    
                    # 转换为字符串并处理NaN值
                    df_str = df.astype(str).replace('nan', '')
                    
                    # 构建工作表文本
                    sheet_text = f"--- 工作表: {sheet_name} ---\n"
                    
                    if not df.empty:
                        if has_header_only:
                            # 只有标题行的情况
                            sheet_text += "标题行: " + " | ".join(str(cell) for cell in df.iloc[0].values if str(cell).strip()) + "\n"
                            sheet_text += "(仅包含标题行，无数据行)\n"
                        else:
                            # 有数据行的情况
                            headers = df.columns.tolist()
                            sheet_text += "列标题: " + " | ".join(str(h) for h in headers) + "\n\n"
                            
                            # 添加数据行（限制显示行数以避免过长）
                            max_rows = 100  # 限制最多显示100行
                            for i, row in df_str.iterrows():
                                if i >= max_rows:
                                    sheet_text += f"... (还有 {len(df) - max_rows} 行数据)\n"
                                    break
                                row_text = " | ".join(str(cell) for cell in row.values if str(cell).strip())
                                if row_text.strip():
                                    sheet_text += f"第{i+1}行: {row_text}\n"
                            
                            if len(df) > max_rows:
                                sheet_text += "\n"
                    else:
                        sheet_text += "(工作表为空)\n"
                    
                    text_parts.append(sheet_text)
                    
                    # 保存工作表数据用于元数据
                    if has_header_only:
                        # 只有标题行的情况
                        sheet_info = {
                            "name": sheet_name,
                            "rows": 1,  # 只有标题行
                            "columns": len(df.columns),
                            "column_names": [str(cell) for cell in df.iloc[0].values if str(cell).strip()],
                            "has_data": True,  # 有标题行也算有数据
                            "has_header_only": True,
                            "non_empty_cells": sum(1 for cell in df.iloc[0].values if str(cell).strip())
                        }
                    else:
                        # 正常情况
                        sheet_info = {
                            "name": sheet_name,
                            "rows": len(df),
                            "columns": len(df.columns),
                            "column_names": df.columns.tolist(),
                            "has_data": not df.empty,
                            "has_header_only": False,
                            "non_empty_cells": df.count().sum()
                        }
                    sheet_data.append(sheet_info)
                    
                except Exception as e:
                    error_text = f"--- 工作表: {sheet_name} (读取失败) ---\n错误: {str(e)}\n"
                    text_parts.append(error_text)
                    sheet_data.append({
                        "name": sheet_name,
                        "error": str(e),
                        "rows": 0,
                        "columns": 0,
                        "has_data": False
                    })
            
            text = "\n\n".join(text_parts)
            
            # 获取基础文件元数据
            base_metadata = self.get_file_metadata(file_path)
            
            # 获取Excel特定元数据
            excel_metadata = self._extract_excel_metadata(target_path, sheet_data)
            
            # 合并元数据
            metadata = {**base_metadata, **excel_metadata}
            
            # 添加文本统计信息
            metadata.update({
                "text_length": len(text),
                "character_count": len(text),
                "word_count": len(text.split()) if text else 0,
                "line_count": text.count('\n') if text else 0
            })
            
            return ParseResult(
                text=text,
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Excel解析失败: {str(e)}"
            logger.error(error_msg)
            traceback.print_exc()
            return self.create_error_result(error_msg, file_path)
        finally:
            # 清理临时文件
            if temp_xlsx_path and os.path.exists(temp_xlsx_path):
                try:
                    os.remove(temp_xlsx_path)
                except Exception:
                    pass
    
    def _convert_xls_to_xlsx(self, file_path: str) -> str:
        """
        使用LibreOffice将XLS转换为XLSX
        """
        xlsx_output_path = file_path + 'x'
        
        # 检查libreoffice是否安装
        try:
            subprocess.run(['libreoffice', '--version'], check=True, capture_output=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise Exception("LibreOffice未安装或不在PATH中，无法转换XLS文件")
            
        logger.info(f"尝试使用LibreOffice将XLS转换为XLSX: {file_path} -> {xlsx_output_path}")
        
        command = [
            'libreoffice',
            '--headless',
            '--convert-to', 'xlsx',
            '--outdir', os.path.dirname(file_path),
            file_path
        ]
        
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"LibreOffice转换错误: {result.stderr}")
            raise Exception(f"LibreOffice转换失败: {result.stderr}")
            
        if not os.path.exists(xlsx_output_path):
             raise Exception(f"转换后的文件未找到: {xlsx_output_path}")
              
        return xlsx_output_path

    def _extract_excel_metadata(self, file_path: str, sheet_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        提取Excel特定元数据
        
        Args:
            file_path: Excel文件路径
            sheet_data: 工作表数据列表
            
        Returns:
            Dict[str, Any]: Excel元数据
        """
        try:
            metadata = {
                "sheet_count": len(sheet_data),
                "sheet_names": [sheet["name"] for sheet in sheet_data],
                "sheets": sheet_data,
                "total_rows": sum(sheet.get("rows", 0) for sheet in sheet_data),
                "total_columns": sum(sheet.get("columns", 0) for sheet in sheet_data),
                "total_non_empty_cells": sum(sheet.get("non_empty_cells", 0) for sheet in sheet_data),
                "has_multiple_sheets": len(sheet_data) > 1,
                "largest_sheet": max(sheet_data, key=lambda x: x.get("rows", 0))["name"] if sheet_data else "",
                "largest_sheet_rows": max(sheet.get("rows", 0) for sheet in sheet_data) if sheet_data else 0
            }
            
            # 尝试获取文档属性（仅适用于.xlsx文件）
            if file_path.lower().endswith('.xlsx'):
                try:
                    wb = openpyxl.load_workbook(file_path, read_only=True)
                    props = wb.properties
                    
                    metadata.update({
                        "title": props.title or '',
                        "author": props.creator or '',
                        "subject": props.subject or '',
                        "keywords": props.keywords or '',
                        "comments": props.description or '',
                        "category": props.category or '',
                        "created": str(props.created) if props.created else '',
                        "modified": str(props.modified) if props.modified else '',
                        "last_modified_by": props.lastModifiedBy or '',
                        "version": props.version or ''
                    })
                except Exception as e:
                    logger.debug(f"获取Excel文档属性失败: {e}")
                    
            return metadata
            
        except Exception as e:
            logger.warning(f"提取Excel元数据失败: {e}")
            return {}
