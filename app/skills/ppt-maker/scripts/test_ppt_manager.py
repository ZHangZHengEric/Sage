#!/usr/bin/env python3
"""
PPT Project Manager 单元测试
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from ppt_manager import (
    PPTProjectManager,
    OperationResult,
    _get_slide_number,
    _format_slide_filename,
    _get_next_slide_number,
    _get_all_slides,
    _get_slide_by_position,
    _dir_is_empty,
)
from html_to_ppt import validate_and_fix_slide_xml


class TestHelperFunctions(unittest.TestCase):
    """测试辅助函数"""

    def test_get_slide_number(self):
        """测试从文件名提取序号"""
        self.assertEqual(_get_slide_number("01-cover.xml"), 1)
        self.assertEqual(_get_slide_number("12-content.xml"), 12)
        self.assertEqual(_get_slide_number("slide.xml"), 0)
        self.assertEqual(_get_slide_number("invalid.xml"), 0)

    def test_format_slide_filename(self):
        """测试格式化文件名"""
        self.assertEqual(_format_slide_filename(1, "cover"), "01-cover.xml")
        self.assertEqual(_format_slide_filename(12), "12-slide.xml")
        self.assertEqual(_format_slide_filename(5, "test-page"), "05-test-page.xml")

    def test_dir_is_empty(self):
        """测试检查目录是否为空"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 空目录
            self.assertTrue(_dir_is_empty(Path(tmp_dir)))
            
            # 非空目录
            test_file = Path(tmp_dir) / "test.txt"
            test_file.write_text("test")
            self.assertFalse(_dir_is_empty(Path(tmp_dir)))
            
            # 不存在的目录
            self.assertTrue(_dir_is_empty(Path(tmp_dir) / "nonexistent"))


class TestValidateAndFixXML(unittest.TestCase):
    """测试 html_to_ppt 中的 validate_and_fix_slide_xml 函数"""

    def test_valid_xml(self):
        """测试有效 XML"""
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">标题</ppt-text>
        </ppt-slide>'''
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertTrue(valid)
        self.assertEqual(fixes, [])
        self.assertIn("<ppt-slide", fixed_xml)

    def test_missing_root(self):
        """测试缺少根节点"""
        xml = "<invalid>content</invalid>"
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertFalse(valid)
        self.assertIn("未找到 <ppt-slide> 根节点", fixes)
        self.assertEqual(fixed_xml, "")

    def test_missing_content(self):
        """测试缺少内容元素"""
        xml = '<ppt-slide width="13.333" height="7.5"></ppt-slide>'
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertFalse(valid)
        self.assertIn("页面缺少内容元素", fixes[0])
        self.assertEqual(fixed_xml, "")

    def test_auto_fix_missing_attributes(self):
        """测试自动修复缺失属性"""
        xml = '''<ppt-slide>
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2">标题</ppt-text>
        </ppt-slide>'''
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertTrue(valid)
        self.assertTrue(any("添加默认 width" in fix for fix in fixes))
        self.assertTrue(any("添加默认 height" in fix for fix in fixes))
        self.assertIn('width="13.333"', fixed_xml)
        self.assertIn('height="7.5"', fixed_xml)

    def test_auto_fix_out_of_bounds(self):
        """测试自动修复超出边界"""
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark">
            <ppt-text class="title" x="20" y="0.9" w="11.333" h="1.2" color="#E5E7EB">标题</ppt-text>
        </ppt-slide>'''
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertTrue(valid)
        self.assertTrue(any("x 坐标" in fix and "已修复" in fix for fix in fixes))
        self.assertIn('x="11.333"', fixed_xml)

    def test_auto_fix_width_overflow(self):
        """测试自动修复宽度溢出"""
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark">
            <ppt-text class="title" x="1" y="0.9" w="20" h="1.2" color="#E5E7EB">标题</ppt-text>
        </ppt-slide>'''
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertTrue(valid)
        self.assertTrue(any("宽度" in fix and "已修复" in fix for fix in fixes))

    def test_auto_fix_missing_color(self):
        """测试自动修复缺失文本颜色"""
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2">标题</ppt-text>
        </ppt-slide>'''
        valid, fixes, fixed_xml = validate_and_fix_slide_xml(xml)
        self.assertTrue(valid)
        self.assertTrue(any("添加默认文本颜色" in fix for fix in fixes))


class TestPPTProjectManager(unittest.TestCase):
    """测试 PPTProjectManager 类"""

    def setUp(self):
        """每个测试前创建临时目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir) / "test_project"

    def tearDown(self):
        """每个测试后清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_project(self):
        """测试项目初始化"""
        manager = PPTProjectManager(self.project_dir)
        result = manager.init(title="测试项目", theme_name="tech-dark")
        
        self.assertTrue(result.success)
        
        # 检查目录结构
        self.assertTrue((self.project_dir / "slides").exists())
        self.assertTrue((self.project_dir / "assets" / "images").exists())
        self.assertTrue((self.project_dir / "themes").exists())
        
        # 检查默认文件
        self.assertTrue((self.project_dir / "slides" / "01-cover.xml").exists())
        self.assertTrue((self.project_dir / "meta.txt").exists())
        self.assertTrue((self.project_dir / "theme.txt").exists())

    def test_add_slide_success(self):
        """测试成功添加页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">新页面</ppt-text>
        </ppt-slide>'''
        
        result = manager.add(name="content", xml_content=xml)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.file_path)
        self.assertTrue(result.file_path.exists())
        # 第一个添加的页面会替换默认封面，所以是 01 而不是 02
        self.assertEqual(result.file_path.name, "01-content.xml")
        # 验证默认封面已被删除
        self.assertFalse((self.project_dir / "slides" / "01-cover.xml").exists())

    def test_add_slide_validation_error(self):
        """测试添加页面验证失败"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        # 无效的 XML（缺少内容元素）
        xml = '<ppt-slide width="13.333" height="7.5"></ppt-slide>'
        
        result = manager.add(name="invalid", xml_content=xml)
        self.assertFalse(result.success)
        self.assertIn("页面缺少内容元素", result.message)
        self.assertTrue(len(result.errors) > 0)

    def test_add_slide_with_auto_fix(self):
        """测试添加页面自动修复"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        # 缺少 width/height 的 XML
        xml = '''<ppt-slide>
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">标题</ppt-text>
        </ppt-slide>'''
        
        result = manager.add(name="fixed", xml_content=xml, auto_fix=True)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.file_path)
        self.assertTrue(result.file_path.exists())
        
        # 检查修复信息
        self.assertTrue(len(result.fixes) > 0)
        
        # 检查修复后的内容
        content = result.file_path.read_text(encoding="utf-8")
        self.assertIn('width="13.333"', content)
        self.assertIn('height="7.5"', content)

    def test_update_slide(self):
        """测试更新页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        # 先添加一个页面（会替换默认封面，成为第1页）
        xml1 = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">旧标题</ppt-text>
        </ppt-slide>'''
        add_result = manager.add(name="content", xml_content=xml1)
        self.assertTrue(add_result.success)
        
        # 更新第 1 页（因为默认封面已被删除）
        xml2 = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">新标题</ppt-text>
        </ppt-slide>'''
        result = manager.update(position=1, xml_content=xml2)
        
        self.assertTrue(result.success)
        self.assertIsNotNone(result.file_path)
        content = result.file_path.read_text(encoding="utf-8")
        self.assertIn("新标题", content)

    def test_update_slide_not_found(self):
        """测试更新不存在的页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">标题</ppt-text>
        </ppt-slide>'''
        
        result = manager.update(position=5, xml_content=xml)
        self.assertFalse(result.success)
        self.assertIn("未找到第 5 页", result.message)

    def test_remove_slide(self):
        """测试删除页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        # 添加两个页面（第一个会替换默认封面）
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">页面</ppt-text>
        </ppt-slide>'''
        result1 = manager.add(name="page2", xml_content=xml)
        result2 = manager.add(name="page3", xml_content=xml)
        self.assertTrue(result1.success)
        self.assertTrue(result2.success)
        
        # 删除第 2 页
        result = manager.remove(position=2)
        self.assertTrue(result.success)
        
        # 检查只剩下 1 页（因为第一个添加的页面替换了默认封面，然后删除了第2页）
        slides = _get_all_slides(manager.slides_dir)
        self.assertEqual(len(slides), 1)

    def test_list_slides(self):
        """测试列出页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        xml = '''<ppt-slide width="13.333" height="7.5" theme="tech-dark" auto-bg="true">
            <ppt-text class="title" x="1" y="0.9" w="11.333" h="1.2" color="#E5E7EB">测试标题</ppt-text>
        </ppt-slide>'''
        result = manager.add(name="test", xml_content=xml)
        self.assertTrue(result.success)
        
        list_result = manager.list_slides()
        self.assertTrue(list_result.success)
        # 第一个添加的页面替换了默认封面，所以只有 1 页
        self.assertIn("共 1 页", list_result.message)

    def test_view_slide(self):
        """测试查看页面"""
        manager = PPTProjectManager(self.project_dir)
        manager.init()
        
        result = manager.view(position=1)
        self.assertTrue(result.success)
        self.assertIn("<ppt-slide", result.message)


class TestSlideOrdering(unittest.TestCase):
    """测试幻灯片排序功能"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.slides_dir = Path(self.temp_dir) / "slides"
        self.slides_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_next_slide_number(self):
        """测试获取下一个序号"""
        self.assertEqual(_get_next_slide_number(self.slides_dir), 1)
        
        # 创建一些文件
        (self.slides_dir / "01-test.xml").write_text("test")
        (self.slides_dir / "03-test.xml").write_text("test")
        
        self.assertEqual(_get_next_slide_number(self.slides_dir), 4)

    def test_get_all_slides(self):
        """测试获取所有幻灯片"""
        # 创建无序的文件
        (self.slides_dir / "03-test.xml").write_text("test")
        (self.slides_dir / "01-test.xml").write_text("test")
        (self.slides_dir / "02-test.xml").write_text("test")
        
        slides = _get_all_slides(self.slides_dir)
        self.assertEqual(len(slides), 3)
        self.assertEqual(_get_slide_number(slides[0].name), 1)
        self.assertEqual(_get_slide_number(slides[1].name), 2)
        self.assertEqual(_get_slide_number(slides[2].name), 3)

    def test_get_slide_by_position(self):
        """测试根据位置获取幻灯片"""
        (self.slides_dir / "01-test.xml").write_text("test")
        (self.slides_dir / "05-test.xml").write_text("test")
        
        slide = _get_slide_by_position(self.slides_dir, 5)
        self.assertIsNotNone(slide)
        self.assertEqual(slide.name, "05-test.xml")
        
        slide = _get_slide_by_position(self.slides_dir, 99)
        self.assertIsNone(slide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
