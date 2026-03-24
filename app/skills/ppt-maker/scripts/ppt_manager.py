#!/usr/bin/env python3
"""
PPT Project Manager - 管理 PPT 项目的完整工具

功能：
- init: 初始化新项目
- add: 添加新页面（自动验证和修复，返回执行结果）
- update: 更新现有页面（自动验证和修复，返回执行结果）
- remove: 删除指定页面
- view: 查看指定页面的 XML 内容
- list: 列出所有页面
- build: 生成 PPT 文件
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# 导入 html_to_ppt 中的功能
sys.path.insert(0, str(Path(__file__).parent))
from html_to_ppt import (
    HtmlPptConverter,
    _extract_slide_fragment,
    validate_and_fix_slide_xml,
)


DEFAULT_SLIDE = """<ppt-slide width="13.333" height="7.5" theme="{theme}" auto-bg="true">
  <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2">
    {title}
  </ppt-text>
  <ppt-text class="subtitle" x="1" y="2.1" w="11.333" h="0.8">
    HTML → Editable PPTX (constrained tags)
  </ppt-text>
  <ppt-rect class="card" x="1" y="3.1" w="11.333" h="3.6"/>
  <ppt-text class="body" x="1.3" y="3.4" w="10.8" h="3.0" pad="0">
    - 用ppt-text/ppt-rect/ppt-table描述元素\\n
    - 坐标单位是英寸\\n
    - 输出PPT文本/表格可编辑
  </ppt-text>
  <ppt-notes>
    讲者备注：这页是可编辑的PPT对象（非PNG）。可以在这里写演讲提示、口播稿、补充数据来源。
  </ppt-notes>
  <!-- DEFAULT_SLIDE_MARKER: This is the auto-generated default slide -->
</ppt-slide>
"""

# 用于识别默认封面的标记
DEFAULT_SLIDE_MARKER = "DEFAULT_SLIDE_MARKER"


@dataclass
class OperationResult:
    """操作结果"""
    success: bool
    message: str
    file_path: Optional[Path] = None
    fixes: list[str] = None
    errors: list[str] = None
    
    def __post_init__(self):
        if self.fixes is None:
            self.fixes = []
        if self.errors is None:
            self.errors = []


def _dir_is_empty(path: Path) -> bool:
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    try:
        return not any(path.iterdir())
    except Exception:
        traceback.print_exc()
        return False


def _get_slide_number(filename: str) -> int:
    """从文件名中提取数字序号"""
    match = re.match(r'^(\d+)', filename)
    if match:
        return int(match.group(1))
    return 0


def _get_slide_name(filename: str) -> Optional[str]:
    """从文件名中提取名称部分（去掉开头的数字序号和扩展名）"""
    # 去掉扩展名
    name_without_ext = filename
    if filename.lower().endswith('.xml'):
        name_without_ext = filename[:-4]
    elif filename.lower().endswith('.html'):
        name_without_ext = filename[:-5]
    elif filename.lower().endswith('.htm'):
        name_without_ext = filename[:-4]

    # 去掉开头的数字序号
    match = re.match(r'^\d+-?(.*)', name_without_ext)
    if match:
        name = match.group(1)
        return name if name else None
    return None


def _format_slide_filename(number: int, name: Optional[str] = None) -> str:
    """格式化幻灯片文件名"""
    if name:
        return f"{number:02d}-{name}.xml"
    return f"{number:02d}-slide.xml"


def _get_next_slide_number(slides_dir: Path) -> int:
    """获取下一个可用的幻灯片序号"""
    if not slides_dir.exists():
        return 1
    max_num = 0
    for f in slides_dir.iterdir():
        if f.suffix.lower() in {".xml", ".html", ".htm"}:
            num = _get_slide_number(f.name)
            max_num = max(max_num, num)
    return max_num + 1


def _get_all_slides(slides_dir: Path) -> list[Path]:
    """获取所有幻灯片文件，按序号排序"""
    if not slides_dir.exists():
        return []
    slides = [f for f in slides_dir.iterdir() if f.suffix.lower() in {".xml", ".html", ".htm"}]
    return sorted(slides, key=lambda x: _get_slide_number(x.name))


def _get_slide_by_position(slides_dir: Path, position: int) -> Optional[Path]:
    """根据位置获取幻灯片文件"""
    for f in slides_dir.iterdir():
        if f.suffix.lower() in {".xml", ".html", ".htm"}:
            if _get_slide_number(f.name) == position:
                return f
    return None


def _reorder_slides(slides_dir: Path) -> None:
    """重新排序所有幻灯片，确保序号连续"""
    slides = _get_all_slides(slides_dir)
    for i, slide in enumerate(slides, 1):
        old_num = _get_slide_number(slide.name)
        if old_num != i:
            rest = slide.name[len(str(old_num)):]
            if rest.startswith('-'):
                rest = rest[1:]
            new_name = _format_slide_filename(i, rest.replace('.xml', '') if rest else None)
            slide.rename(slides_dir / new_name)
            print(f"  重命名: {slide.name} -> {new_name}")


def _render_validate(project_dir: Path, specific_slide: Optional[Path] = None) -> tuple[bool, list[str]]:
    """
    使用 HtmlPptConverter 进行渲染验证
    返回: (是否成功, 错误信息列表)
    """
    errors = []
    
    try:
        with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as tmp:
            tmp_path = tmp.name
        
        if specific_slide:
            # 创建临时项目，只包含要验证的页面
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_project = Path(tmp_dir) / "project"
                tmp_slides = tmp_project / "slides"
                tmp_slides.mkdir(parents=True)
                
                # 复制主题文件
                themes_dir = project_dir / "themes"
                if themes_dir.exists():
                    shutil.copytree(themes_dir, tmp_project / "themes", dirs_exist_ok=True)
                
                # 复制 theme.txt
                theme_txt = project_dir / "theme.txt"
                if theme_txt.exists():
                    shutil.copy2(theme_txt, tmp_project / "theme.txt")
                
                # 只复制要验证的页面
                shutil.copy2(specific_slide, tmp_slides / specific_slide.name)
                
                # 使用临时项目进行验证
                converter = HtmlPptConverter(tmp_project, verbose=False)
                converter.convert(Path(tmp_path))
                errors.extend(converter.validation_errors)
        else:
            converter = HtmlPptConverter(project_dir, verbose=False)
            converter.convert(Path(tmp_path))
            errors.extend(converter.validation_errors)
        
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
            
    except Exception as e:
        # 如果 convert 抛出异常，说明有严重错误
        error_msg = str(e)
        if "发现布局问题" in error_msg and errors:
            # 布局问题已经在 validation_errors 中
            pass
        else:
            errors.append(f"渲染验证失败: {e}")
    
    return len(errors) == 0, errors


class PPTProjectManager:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.slides_dir = self.project_dir / "slides"
        self.assets_dir = self.project_dir / "assets"
        self.themes_dir = self.project_dir / "themes"
        self._theme_name = self._load_theme_name()

    def _load_theme_name(self) -> str:
        """加载项目主题名称"""
        theme_txt = self.project_dir / "theme.txt"
        if theme_txt.exists():
            try:
                raw = theme_txt.read_text(encoding="utf-8")
                for line in raw.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.lower().startswith("theme="):
                        return s.split("=", 1)[1].strip().lower() or "tech-dark"
            except Exception:
                pass
        return "tech-dark"
    
    def init(self, title: Optional[str] = None, theme_name: str = "tech-dark") -> OperationResult:
        """初始化新项目"""
        try:
            if self.project_dir.exists() and not self.project_dir.is_dir():
                return OperationResult(
                    success=False,
                    message=f"目标路径已存在且不是目录: {self.project_dir}",
                    errors=[f"目标路径已存在且不是目录: {self.project_dir}"]
                )
            
            if self.project_dir.exists() and not _dir_is_empty(self.project_dir):
                return OperationResult(
                    success=False,
                    message=f"目录已存在且非空: {self.project_dir}",
                    errors=[f"目录已存在且非空: {self.project_dir}"]
                )
            
            images_dir = self.assets_dir / "images"
            self.slides_dir.mkdir(parents=True, exist_ok=True)
            images_dir.mkdir(parents=True, exist_ok=True)
            self.themes_dir.mkdir(parents=True, exist_ok=True)
            
            slide_01 = self.slides_dir / "01-cover.xml"
            if not slide_01.exists():
                slide_title = title or self.project_dir.name
                slide_01.write_text(DEFAULT_SLIDE.format(title=slide_title, theme=theme_name), encoding="utf-8")
            
            meta = self.project_dir / "meta.txt"
            if not meta.exists():
                meta.write_text(
                    f"created_at={datetime.now().isoformat(timespec='seconds')}\n"
                    f"title={title or self.project_dir.name}\n",
                    encoding="utf-8",
                )
            
            theme = self.project_dir / "theme.txt"
            theme.write_text(f"theme={theme_name}\n", encoding="utf-8")
            
            src_css = Path(__file__).resolve().parent.parent / "themes" / f"{theme_name}.css"
            if src_css.exists():
                dst_css = self.themes_dir / src_css.name
                if not dst_css.exists():
                    shutil.copy2(src_css, dst_css)
            
            return OperationResult(
                success=True,
                message=f"项目已初始化: {self.project_dir}",
                file_path=self.project_dir
            )
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"初始化失败: {e}",
                errors=[str(e)]
            )
    
    def add(self, name: str, xml_content: str, auto_fix: bool = True) -> OperationResult:
        """
        添加新页面（自动验证和修复）
        
        Args:
            name: 页面名称（用于文件名）
            xml_content: XML 内容
            auto_fix: 是否自动修复可修复的问题
        
        Returns:
            OperationResult 包含执行结果、修复信息、错误详情等
        """
        # 使用 html_to_ppt 的验证和修复功能
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml_content, self._theme_name)
        
        if not valid:
            # 验证失败，返回详细错误信息，引导 Agent 调整
            error_msg = "XML 验证失败，请根据以下错误调整:\n"
            for fix in fixes:
                error_msg += f"  - {fix}\n"
            error_msg += "\n建议:\n"
            error_msg += "  1. 确保 XML 包含 <ppt-slide> 根节点\n"
            error_msg += "  2. 确保包含至少一个内容元素 (ppt-text/ppt-rect/ppt-table/ppt-chart/ppt-image)\n"
            error_msg += "  3. 检查 XML 语法是否正确"
            
            return OperationResult(
                success=False,
                message=error_msg,
                errors=fixes,
                fixes=[]
            )
        
        # 如果有修复，使用修复后的内容
        if auto_fix and fixed_xml and fixes:
            xml_content = fixed_xml
        
        next_num = _get_next_slide_number(self.slides_dir)
        target_file = self.slides_dir / _format_slide_filename(next_num, name)
        
        # 先写入临时文件进行渲染验证
        temp_file = self.slides_dir / f".temp_{next_num}_{name}.xml"
        temp_file.write_text(xml_content, encoding="utf-8")
        
        try:
            # 渲染验证（使用 HtmlPptConverter 的完整验证）
            success, errors = _render_validate(self.project_dir, temp_file)
            if not success:
                temp_file.unlink()
                
                # 构建引导性错误信息
                error_msg = "页面渲染验证失败，未添加。请根据以下错误调整 XML:\n"
                for err in errors:
                    error_msg += f"  - {err}\n"
                error_msg += "\n建议调整:\n"
                error_msg += "  1. 检查元素坐标和尺寸是否超出幻灯片边界\n"
                error_msg += "  2. 检查颜色对比度是否足够\n"
                error_msg += "  3. 检查表格结构是否正确\n"
                error_msg += "  4. 确保所有必需的属性都已设置"
                
                return OperationResult(
                    success=False,
                    message=error_msg,
                    errors=errors,
                    fixes=fixes if auto_fix else []
                )
            
            # 验证通过，重命名为正式文件
            temp_file.rename(target_file)
            
            # 检查是否存在默认封面页（通过内容标记判断），如果存在则删除并用当前页面替换
            default_slide = self.slides_dir / "01-cover.xml"
            deleted_default = False
            if default_slide.exists():
                # 读取内容检查是否是默认封面
                try:
                    content = default_slide.read_text(encoding="utf-8")
                    if DEFAULT_SLIDE_MARKER in content:
                        # 是默认封面，删除它
                        default_slide.unlink()
                        # 重命名当前页面为01
                        new_name = self.slides_dir / _format_slide_filename(1, name)
                        target_file.rename(new_name)
                        target_file = new_name
                        deleted_default = True
                except Exception:
                    # 读取失败，不删除
                    pass
            
            success_msg = f"已添加页面: {target_file.name}"
            if deleted_default:
                success_msg += "\n已删除默认封面页"
            if fixes and auto_fix:
                success_msg += "\n自动修复的问题:\n"
                for fix in fixes:
                    success_msg += f"  - {fix}\n"
            
            return OperationResult(
                success=True,
                message=success_msg,
                file_path=target_file,
                fixes=fixes if auto_fix else []
            )
            
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            return OperationResult(
                success=False,
                message=f"添加页面时发生错误: {e}",
                errors=[str(e)],
                fixes=fixes if auto_fix else []
            )
    
    def update(self, position: int, xml_content: str, auto_fix: bool = True) -> OperationResult:
        """
        更新现有页面（自动验证和修复）
        
        Args:
            position: 页面位置（1-based）
            xml_content: 新的 XML 内容
            auto_fix: 是否自动修复可修复的问题
        
        Returns:
            OperationResult 包含执行结果、修复信息、错误详情等
        """
        target_file = _get_slide_by_position(self.slides_dir, position)
        if not target_file:
            return OperationResult(
                success=False,
                message=f"未找到第 {position} 页",
                errors=[f"未找到第 {position} 页"]
            )
        
        # 使用 html_to_ppt 的验证和修复功能
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml_content, self._theme_name)
        
        if not valid:
            # 验证失败，返回详细错误信息
            error_msg = "XML 验证失败，请根据以下错误调整:\n"
            for fix in fixes:
                error_msg += f"  - {fix}\n"
            error_msg += "\n建议:\n"
            error_msg += "  1. 确保 XML 包含 <ppt-slide> 根节点\n"
            error_msg += "  2. 确保包含至少一个内容元素 (ppt-text/ppt-rect/ppt-table/ppt-chart/ppt-image)\n"
            error_msg += "  3. 检查 XML 语法是否正确"
            
            return OperationResult(
                success=False,
                message=error_msg,
                errors=fixes,
                fixes=[]
            )
        
        # 如果有修复，使用修复后的内容
        if auto_fix and fixed_xml and fixes:
            xml_content = fixed_xml
        
        # 备份原文件
        backup = self.slides_dir / f"{target_file.stem}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
        shutil.copy2(target_file, backup)
        
        # 写入临时文件进行渲染验证
        temp_file = self.slides_dir / f".temp_update_{position}.xml"
        temp_file.write_text(xml_content, encoding="utf-8")
        
        try:
            # 渲染验证
            success, errors = _render_validate(self.project_dir, temp_file)
            if not success:
                temp_file.unlink()
                
                # 构建引导性错误信息
                error_msg = "页面渲染验证失败，未更新。请根据以下错误调整 XML:\n"
                for err in errors:
                    error_msg += f"  - {err}\n"
                error_msg += "\n建议调整:\n"
                error_msg += "  1. 检查元素坐标和尺寸是否超出幻灯片边界\n"
                error_msg += "  2. 检查颜色对比度是否足够\n"
                error_msg += "  3. 检查表格结构是否正确\n"
                error_msg += "  4. 确保所有必需的属性都已设置"
                
                return OperationResult(
                    success=False,
                    message=error_msg,
                    errors=errors,
                    fixes=fixes if auto_fix else []
                )
            
            # 验证通过，替换原文件
            temp_file.rename(target_file)
            
            success_msg = f"已更新第 {position} 页: {target_file.name}\n原文件已备份: {backup.name}"
            if fixes and auto_fix:
                success_msg += "\n自动修复的问题:\n"
                for fix in fixes:
                    success_msg += f"  - {fix}\n"
            
            return OperationResult(
                success=True,
                message=success_msg,
                file_path=target_file,
                fixes=fixes if auto_fix else []
            )
            
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            return OperationResult(
                success=False,
                message=f"更新页面时发生错误: {e}",
                errors=[str(e)],
                fixes=fixes if auto_fix else []
            )
    
    def insert(self, position: int, name: str, xml_content: str, auto_fix: bool = True) -> OperationResult:
        """
        在指定位置插入新页面（自动验证和修复）
        插入后，该位置及之后的页面序号会自动后移

        Args:
            position: 插入位置（1-based，插入到该位置之前）
            name: 页面名称（用于文件名）
            xml_content: XML 内容
            auto_fix: 是否自动修复可修复的问题

        Returns:
            OperationResult 包含执行结果、修复信息、错误详情等
        """
        # 使用 html_to_ppt 的验证和修复功能
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml_content, self._theme_name)

        if not valid:
            # 验证失败，返回详细错误信息，引导 Agent 调整
            error_msg = "XML 验证失败，请根据以下错误调整:\n"
            for fix in fixes:
                error_msg += f"  - {fix}\n"
            error_msg += "\n建议:\n"
            error_msg += "  1. 确保 XML 包含 <ppt-slide> 根节点\n"
            error_msg += "  2. 确保包含至少一个内容元素 (ppt-text/ppt-rect/ppt-table/ppt-chart/ppt-image)\n"
            error_msg += "  3. 检查 XML 语法是否正确"

            return OperationResult(
                success=False,
                message=error_msg,
                errors=fixes,
                fixes=[]
            )

        # 如果有修复，使用修复后的内容
        if auto_fix and fixed_xml and fixes:
            xml_content = fixed_xml

        # 获取所有现有幻灯片
        slides = _get_all_slides(self.slides_dir)
        total_slides = len(slides)

        # 验证位置有效性
        if position < 1:
            position = 1
        if position > total_slides + 1:
            position = total_slides + 1

        try:
            # 创建临时目录用于存储文件
            temp_dir = self.slides_dir / ".temp_insert"
            temp_dir.mkdir(exist_ok=True)

            # 将插入位置及之后的文件移动到临时目录，并增加序号
            for slide in reversed(slides):
                slide_num = _get_slide_number(slide.name)
                if slide_num >= position:
                    # 提取文件名中的名称部分
                    slide_name = _get_slide_name(slide.name)
                    # 新的序号
                    new_num = slide_num + 1
                    new_name = _format_slide_filename(new_num, slide_name)
                    # 先移动到临时目录
                    temp_file = temp_dir / new_name
                    shutil.move(str(slide), str(temp_file))

            # 确定新文件的名称
            target_file = self.slides_dir / _format_slide_filename(position, name)

            # 写入临时文件进行渲染验证
            temp_file = self.slides_dir / f".temp_insert_{position}_{name}.xml"
            temp_file.write_text(xml_content, encoding="utf-8")

            try:
                # 渲染验证（使用 HtmlPptConverter 的完整验证）
                success, errors = _render_validate(self.project_dir, temp_file)
                if not success:
                    temp_file.unlink()
                    # 恢复原来的文件
                    for temp_f in temp_dir.iterdir():
                        if temp_f.is_file():
                            original_num = _get_slide_number(temp_f.name) - 1
                            slide_name = _get_slide_name(temp_f.name)
                            original_name = _format_slide_filename(original_num, slide_name)
                            shutil.move(str(temp_f), str(self.slides_dir / original_name))
                    temp_dir.rmdir()

                    # 构建引导性错误信息
                    error_msg = "页面渲染验证失败，未插入。请根据以下错误调整 XML:\n"
                    for err in errors:
                        error_msg += f"  - {err}\n"
                    error_msg += "\n建议调整:\n"
                    error_msg += "  1. 检查元素坐标和尺寸是否超出幻灯片边界\n"
                    error_msg += "  2. 检查颜色对比度是否足够\n"
                    error_msg += "  3. 检查表格结构是否正确\n"
                    error_msg += "  4. 确保所有必需的属性都已设置"

                    return OperationResult(
                        success=False,
                        message=error_msg,
                        errors=errors,
                        fixes=fixes if auto_fix else []
                    )

                # 验证通过，重命名为正式文件
                temp_file.rename(target_file)

                # 将临时目录中的文件移回 slides 目录
                for temp_f in temp_dir.iterdir():
                    if temp_f.is_file():
                        shutil.move(str(temp_f), str(self.slides_dir / temp_f.name))

                # 删除临时目录
                temp_dir.rmdir()

                success_msg = f"已在第 {position} 位插入页面: {target_file.name}"
                if fixes and auto_fix:
                    success_msg += "\n自动修复的问题:\n"
                    for fix in fixes:
                        success_msg += f"  - {fix}\n"

                return OperationResult(
                    success=True,
                    message=success_msg,
                    file_path=target_file,
                    fixes=fixes if auto_fix else []
                )

            except Exception as e:
                # 清理临时文件
                if temp_file.exists():
                    temp_file.unlink()
                # 恢复原来的文件
                for temp_f in temp_dir.iterdir():
                    if temp_f.is_file():
                        original_num = _get_slide_number(temp_f.name) - 1
                        slide_name = _get_slide_name(temp_f.name)
                        original_name = _format_slide_filename(original_num, slide_name)
                        shutil.move(str(temp_f), str(self.slides_dir / original_name))
                temp_dir.rmdir()

                return OperationResult(
                    success=False,
                    message=f"插入页面时发生错误: {e}",
                    errors=[str(e)],
                    fixes=fixes if auto_fix else []
                )

        except Exception as e:
            return OperationResult(
                success=False,
                message=f"插入页面时发生错误: {e}",
                errors=[str(e)],
                fixes=fixes if auto_fix else []
            )

    def remove(self, position: int, reorder: bool = True) -> OperationResult:
        """删除指定位置的页面"""
        target_file = _get_slide_by_position(self.slides_dir, position)
        if not target_file:
            return OperationResult(
                success=False,
                message=f"未找到第 {position} 页",
                errors=[f"未找到第 {position} 页"]
            )

        try:
            trash_dir = self.project_dir / ".trash"
            trash_dir.mkdir(exist_ok=True)
            trash_file = trash_dir / f"{target_file.stem}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            shutil.move(str(target_file), str(trash_file))

            if reorder:
                _reorder_slides(self.slides_dir)

            return OperationResult(
                success=True,
                message=f"已删除第 {position} 页: {target_file.name}\n已移动到: {trash_file}",
                file_path=trash_file
            )
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"删除页面时发生错误: {e}",
                errors=[str(e)]
            )
    
    def view(self, position: int) -> OperationResult:
        """查看指定页面的 XML 内容"""
        target_file = _get_slide_by_position(self.slides_dir, position)
        if not target_file:
            return OperationResult(
                success=False,
                message=f"未找到第 {position} 页",
                errors=[f"未找到第 {position} 页"]
            )
        
        try:
            content = target_file.read_text(encoding="utf-8")
            return OperationResult(
                success=True,
                message=f"=== {target_file.name} ===\n{content}",
                file_path=target_file
            )
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"读取页面内容时发生错误: {e}",
                errors=[str(e)]
            )
    
    def list_slides(self) -> OperationResult:
        """列出所有页面"""
        try:
            slides = _get_all_slides(self.slides_dir)
            if not slides:
                return OperationResult(
                    success=True,
                    message="项目中暂无页面",
                    file_path=self.slides_dir
                )
            
            message = f"共 {len(slides)} 页:\n"
            for i, slide in enumerate(slides, 1):
                try:
                    content = slide.read_text(encoding="utf-8")
                    fragment = _extract_slide_fragment(content)
                    if fragment:
                        root = ET.fromstring(fragment)
                        title = ""
                        for child in root:
                            if (child.tag or "").strip().lower() == "ppt-text":
                                cls = child.attrib.get("class", "")
                                if "title" in cls.lower():
                                    title = "".join(child.itertext()).strip()[:30]
                                    break
                        if title:
                            message += f"  {i}. {slide.name} - {title}...\n"
                        else:
                            message += f"  {i}. {slide.name}\n"
                    else:
                        message += f"  {i}. {slide.name}\n"
                except Exception:
                    message += f"  {i}. {slide.name}\n"
            
            return OperationResult(
                success=True,
                message=message,
                file_path=self.slides_dir
            )
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"列出页面时发生错误: {e}",
                errors=[str(e)]
            )
    
    def build(self, output_file: Optional[Path] = None) -> OperationResult:
        """生成 PPT 文件"""
        if output_file is None:
            output_file = self.project_dir / "presentation.pptx"
        
        try:
            converter = HtmlPptConverter(self.project_dir, verbose=True)
            result = converter.convert(output_file)
            return OperationResult(
                success=True,
                message=f"PPT 生成成功: {result}",
                file_path=result
            )
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"生成 PPT 时发生错误: {e}",
                errors=[str(e)]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PPT Project Manager - 管理 PPT 项目的完整工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 初始化项目
  %(prog)s init /path/to/project --theme tech-dark

  # 添加新页面（自动验证，添加到末尾）
  %(prog)s add /path/to/project --name "content" --xml '<ppt-slide>...</ppt-slide>'

  # 更新第 3 页
  %(prog)s update /path/to/project --position 3 --xml '<ppt-slide>...</ppt-slide>'

  # 在第 2 页前插入新页面
  %(prog)s insert /path/to/project --position 2 --name "new_slide" --xml '<ppt-slide>...</ppt-slide>'

  # 删除第 5 页
  %(prog)s remove /path/to/project --position 5

  # 查看第 2 页
  %(prog)s view /path/to/project --position 2

  # 列出所有页面
  %(prog)s list /path/to/project

  # 生成 PPT
  %(prog)s build /path/to/project --out result.pptx
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    init_parser = subparsers.add_parser("init", help="初始化新项目")
    init_parser.add_argument("project_dir", help="项目目录路径")
    init_parser.add_argument("--title", default=None, help="演示文稿标题（默认：目录名）")
    init_parser.add_argument("--theme", default="tech-dark", help="主题名称（css 文件名，不含扩展名）")
    
    add_parser = subparsers.add_parser("add", help="添加新页面（自动验证）")
    add_parser.add_argument("project_dir", help="项目目录路径")
    add_parser.add_argument("--name", "-n", required=True, help="页面名称（用于文件名）")
    add_parser.add_argument("--xml", default=None, help="XML 内容（直接传入）")
    add_parser.add_argument("--file", "-f", type=Path, default=None, help="XML 文件路径")
    
    update_parser = subparsers.add_parser("update", help="更新现有页面（自动验证）")
    update_parser.add_argument("project_dir", help="项目目录路径")
    update_parser.add_argument("--position", "-p", type=int, required=True, help="页面位置（1-based）")
    update_parser.add_argument("--xml", default=None, help="XML 内容（直接传入）")
    update_parser.add_argument("--file", "-f", type=Path, default=None, help="XML 文件路径")

    insert_parser = subparsers.add_parser("insert", help="在指定位置插入新页面（自动验证）")
    insert_parser.add_argument("project_dir", help="项目目录路径")
    insert_parser.add_argument("--position", "-p", type=int, required=True, help="插入位置（1-based，插入到该位置之前）")
    insert_parser.add_argument("--name", "-n", required=True, help="页面名称（用于文件名）")
    insert_parser.add_argument("--xml", default=None, help="XML 内容（直接传入）")
    insert_parser.add_argument("--file", "-f", type=Path, default=None, help="XML 文件路径")

    remove_parser = subparsers.add_parser("remove", help="删除页面")
    remove_parser.add_argument("project_dir", help="项目目录路径")
    remove_parser.add_argument("--position", "-p", type=int, required=True, help="要删除的页面位置（1-based）")
    remove_parser.add_argument("--no-reorder", action="store_true", help="删除后不重新排序")
    
    view_parser = subparsers.add_parser("view", help="查看页面内容")
    view_parser.add_argument("project_dir", help="项目目录路径")
    view_parser.add_argument("--position", "-p", type=int, required=True, help="要查看的页面位置（1-based）")
    
    list_parser = subparsers.add_parser("list", help="列出所有页面")
    list_parser.add_argument("project_dir", help="项目目录路径")
    
    build_parser = subparsers.add_parser("build", help="生成 PPT 文件")
    build_parser.add_argument("project_dir", help="项目目录路径")
    build_parser.add_argument("--out", "-o", type=Path, default=None, help="输出文件路径（默认：项目目录/presentation.pptx）")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        project_dir = Path(os.path.abspath(args.project_dir))
        
        if args.command == "init":
            manager = PPTProjectManager(project_dir)
            title = args.title or project_dir.name
            result = manager.init(title, str(args.theme).strip().lower() or "tech-dark")
            print(result.message)
            sys.exit(0 if result.success else 1)
        
        elif args.command == "add":
            manager = PPTProjectManager(project_dir)
            
            xml_content = None
            if args.xml:
                xml_content = args.xml
            elif args.file:
                xml_content = args.file.read_text(encoding="utf-8")
            else:
                print("错误: 必须提供 --xml 或 --file 参数", file=sys.stderr)
                sys.exit(1)
            
            result = manager.add(name=args.name, xml_content=xml_content)
            print(result.message)
            sys.exit(0 if result.success else 1)
        
        elif args.command == "update":
            manager = PPTProjectManager(project_dir)

            xml_content = None
            if args.xml:
                xml_content = args.xml
            elif args.file:
                xml_content = args.file.read_text(encoding="utf-8")
            else:
                print("错误: 必须提供 --xml 或 --file 参数", file=sys.stderr)
                sys.exit(1)

            result = manager.update(position=args.position, xml_content=xml_content)
            print(result.message)
            sys.exit(0 if result.success else 1)

        elif args.command == "insert":
            manager = PPTProjectManager(project_dir)

            xml_content = None
            if args.xml:
                xml_content = args.xml
            elif args.file:
                xml_content = args.file.read_text(encoding="utf-8")
            else:
                print("错误: 必须提供 --xml 或 --file 参数", file=sys.stderr)
                sys.exit(1)

            result = manager.insert(position=args.position, name=args.name, xml_content=xml_content)
            print(result.message)
            sys.exit(0 if result.success else 1)

        elif args.command == "remove":
            manager = PPTProjectManager(project_dir)
            result = manager.remove(args.position, reorder=not args.no_reorder)
            print(result.message)
            sys.exit(0 if result.success else 1)
        
        elif args.command == "view":
            manager = PPTProjectManager(project_dir)
            result = manager.view(args.position)
            print(result.message)
            sys.exit(0 if result.success else 1)
        
        elif args.command == "list":
            manager = PPTProjectManager(project_dir)
            result = manager.list_slides()
            print(result.message)
            sys.exit(0 if result.success else 1)
        
        elif args.command == "build":
            manager = PPTProjectManager(project_dir)
            result = manager.build(args.out)
            print(result.message)
            sys.exit(0 if result.success else 1)
    
    except Exception as e:
        traceback.print_exc()
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
