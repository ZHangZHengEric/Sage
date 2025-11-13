"""
HTML文件解析器
支持HTML文件的文本提取和元数据获取
"""

import traceback
from typing import Dict, Any, List
from bs4 import BeautifulSoup
import html2text
import re
from .base_parser import BaseFileParser, ParseResult


class HTMLParser(BaseFileParser):
    """HTML文件解析器"""
    
    SUPPORTED_EXTENSIONS = ['.html', '.htm']
    SUPPORTED_MIME_TYPES = ['text/html']
    
    def parse(self, file_path: str, skip_validation: bool = False) -> ParseResult:
        """
        解析HTML文件
        
        Args:
            file_path: HTML文件路径
            skip_validation: 是否跳过文件格式验证（can_parse检查）
            
        Returns:
            ParseResult: 解析结果
        """
        if not self.validate_file(file_path):
            return self.create_error_result(f"文件不存在或无法读取: {file_path}", file_path)
        
        if not skip_validation and not self.can_parse(file_path):
            return self.create_error_result(f"不支持的文件类型: {file_path}", file_path)
        
        try:
            # 读取HTML文件
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                html_content = file.read()
            
            # 解析HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 提取纯文本内容
            text = self._extract_text_content(soup)
            
            # 获取基础文件元数据
            base_metadata = self.get_file_metadata(file_path)
            
            # 获取HTML特定元数据
            html_metadata = self._extract_html_metadata(soup, html_content)
            
            # 合并元数据
            metadata = {**base_metadata, **html_metadata}
            
            # 添加文本统计信息
            metadata.update({
                "text_length": len(text),
                "character_count": len(text),
                "word_count": len(text.split()) if text else 0,
                "line_count": text.count('\\n') if text else 0
            })
            
            return ParseResult(
                text=text,
                metadata=metadata,
                success=True
            )
            
        except Exception as e:
            error_msg = f"HTML解析失败: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            return self.create_error_result(error_msg, file_path)
    
    def _extract_text_content(self, soup: BeautifulSoup) -> str:
        """
        提取HTML的文本内容
        
        Args:
            soup: BeautifulSoup对象
            
        Returns:
            str: 提取的文本内容
        """
        try:
            # 移除script和style标签
            for script in soup(["script", "style"]):
                script.decompose()
            
            # 使用html2text转换为Markdown格式的文本
            h = html2text.HTML2Text()
            h.ignore_links = False  # 保留链接信息
            h.ignore_images = False  # 保留图片信息
            h.body_width = 0  # 不限制行宽
            
            text = h.handle(str(soup))
            
            # 清理多余的空行
            text = re.sub(r'\\n\\s*\\n', '\\n\\n', text)
            text = text.strip()
            
            return text
            
        except Exception as e:
            print(f"提取HTML文本内容时出错: {e}")
            traceback.print_exc()
            # 降级到简单文本提取
            return soup.get_text(separator='\\n', strip=True)
    
    def _extract_html_metadata(self, soup: BeautifulSoup, html_content: str) -> Dict[str, Any]:
        """
        提取HTML特定元数据
        
        Args:
            soup: BeautifulSoup对象
            html_content: 原始HTML内容
            
        Returns:
            Dict[str, Any]: HTML元数据
        """
        try:
            metadata = {}
            
            # 提取基本HTML信息
            metadata["html_length"] = len(html_content)
            metadata["doctype"] = self._extract_doctype(html_content)
            
            # 提取head信息
            head = soup.find('head')
            if head:
                # 标题
                title_tag = head.find('title')
                metadata["title"] = title_tag.get_text(strip=True) if title_tag else ''
                
                # Meta标签信息
                meta_tags = head.find_all('meta')
                meta_info = {}
                for meta in meta_tags:
                    name = meta.get('name') or meta.get('property') or meta.get('http-equiv')
                    content = meta.get('content')
                    if name and content:
                        meta_info[name] = content
                
                metadata["meta_tags"] = meta_info
                metadata["description"] = meta_info.get('description', '')
                metadata["keywords"] = meta_info.get('keywords', '')
                metadata["author"] = meta_info.get('author', '')
                metadata["viewport"] = meta_info.get('viewport', '')
                
                # 链接信息
                links = head.find_all('link')
                stylesheets = []
                for link in links:
                    if link.get('rel') == ['stylesheet'] or 'stylesheet' in (link.get('rel') or []):
                        stylesheets.append(link.get('href', ''))
                metadata["stylesheets"] = stylesheets
                metadata["stylesheet_count"] = len(stylesheets)
                
                # 脚本信息
                scripts = head.find_all('script')
                script_sources = []
                inline_scripts = 0
                for script in scripts:
                    src = script.get('src')
                    if src:
                        script_sources.append(src)
                    else:
                        inline_scripts += 1
                metadata["external_scripts"] = script_sources
                metadata["external_script_count"] = len(script_sources)
                metadata["inline_script_count"] = inline_scripts
            
            # 提取body信息
            body = soup.find('body')
            if body:
                # 统计各种HTML元素
                metadata["heading_counts"] = {
                    f"h{i}": len(body.find_all(f'h{i}')) for i in range(1, 7)
                }
                metadata["paragraph_count"] = len(body.find_all('p'))
                metadata["link_count"] = len(body.find_all('a'))
                metadata["image_count"] = len(body.find_all('img'))
                metadata["table_count"] = len(body.find_all('table'))
                metadata["form_count"] = len(body.find_all('form'))
                metadata["list_count"] = len(body.find_all(['ul', 'ol']))
                metadata["div_count"] = len(body.find_all('div'))
                
                # 提取所有链接
                links = body.find_all('a', href=True)
                link_urls = [link['href'] for link in links]
                metadata["links"] = link_urls[:50]  # 限制链接数量
                metadata["total_link_count"] = len(link_urls)
                
                # 提取所有图片
                images = body.find_all('img', src=True)
                image_sources = [img['src'] for img in images]
                metadata["images"] = image_sources[:20]  # 限制图片数量
                metadata["total_image_count"] = len(image_sources)
                
                # 提取表格信息
                tables = body.find_all('table')
                table_info = []
                for i, table in enumerate(tables[:5]):  # 限制表格数量
                    rows = table.find_all('tr')
                    table_info.append({
                        "index": i + 1,
                        "rows": len(rows),
                        "columns": len(rows[0].find_all(['td', 'th'])) if rows else 0
                    })
                metadata["table_details"] = table_info
            
            # 语言信息
            html_tag = soup.find('html')
            if html_tag:
                metadata["language"] = html_tag.get('lang', '')
            
            # 字符编码
            charset_meta = soup.find('meta', attrs={'charset': True})
            if charset_meta:
                metadata["charset"] = charset_meta.get('charset', '')
            else:
                http_equiv_meta = soup.find('meta', attrs={'http-equiv': 'Content-Type'})
                if http_equiv_meta:
                    content = http_equiv_meta.get('content', '')
                    charset_match = re.search(r'charset=([^;\\s]+)', content)
                    metadata["charset"] = charset_match.group(1) if charset_match else ''
            
            return metadata
            
        except Exception as e:
            print(f"提取HTML元数据时出错: {e}")
            traceback.print_exc()
            return {"metadata_extraction_error": str(e)}
    
    def _extract_doctype(self, html_content: str) -> str:
        """
        提取HTML文档类型声明
        
        Args:
            html_content: HTML内容
            
        Returns:
            str: DOCTYPE声明
        """
        try:
            doctype_match = re.search(r'<!DOCTYPE[^>]*>', html_content, re.IGNORECASE)
            return doctype_match.group(0) if doctype_match else ''
        except Exception:
            return ''