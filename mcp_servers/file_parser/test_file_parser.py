#!/usr/bin/env python3
"""
文件解析器测试脚本
测试所有文件解析功能
"""

import asyncio
import sys
import os
import json
import tempfile
import time
from pathlib import Path

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from file_parser import (
    extract_text_from_file,
    extract_text_from_url,
    get_supported_formats,
    validate_file_format,
    batch_extract_text
)

class FileParserTestSuite:
    """文件解析器测试套件"""
    
    def __init__(self):
        self.test_results = []
        self.passed = 0
        self.failed = 0
        self.temp_dir = None
    
    def setup_test_files(self):
        """创建测试文件"""
        self.temp_dir = tempfile.mkdtemp()
        test_files = {}
        
        # 创建测试文本文件
        txt_file = os.path.join(self.temp_dir, "test.txt")
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write("这是一个测试文本文件。\n包含多行内容。\n用于测试文件解析功能。")
        test_files['txt'] = txt_file
        
        # 创建测试JSON文件
        json_file = os.path.join(self.temp_dir, "test.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                "name": "测试数据",
                "type": "JSON文件",
                "content": ["项目1", "项目2", "项目3"]
            }, f, ensure_ascii=False, indent=2)
        test_files['json'] = json_file
        
        # 创建测试CSV文件
        csv_file = os.path.join(self.temp_dir, "test.csv")
        with open(csv_file, 'w', encoding='utf-8') as f:
            f.write("姓名,年龄,城市\n")
            f.write("张三,25,北京\n")
            f.write("李四,30,上海\n")
            f.write("王五,28,广州\n")
        test_files['csv'] = csv_file
        
        # 创建测试Markdown文件
        md_file = os.path.join(self.temp_dir, "test.md")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write("# 测试Markdown文件\n\n")
            f.write("这是一个**测试**文档。\n\n")
            f.write("## 功能列表\n\n")
            f.write("- 功能1\n")
            f.write("- 功能2\n")
            f.write("- 功能3\n")
        test_files['md'] = md_file
        
        # 创建测试HTML文件
        html_file = os.path.join(self.temp_dir, "test.html")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>测试HTML页面</title>
            </head>
            <body>
                <h1>欢迎来到测试页面</h1>
                <p>这是一个测试段落，包含<strong>粗体文本</strong>和<em>斜体文本</em>。</p>
                <ul>
                    <li>列表项目1</li>
                    <li>列表项目2</li>
                    <li>列表项目3</li>
                </ul>
            </body>
            </html>
            """)
        test_files['html'] = html_file
        
        return test_files
    
    def cleanup_test_files(self):
        """清理测试文件"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    async def run_test(self, test_name: str, test_func, *args, **kwargs):
        """运行单个测试"""
        print(f"\n🧪 测试: {test_name}")
        print("-" * 50)
        
        try:
            result = await test_func(*args, **kwargs)
            
            if isinstance(result, dict) and result.get("status") == "success":
                print(f"✅ {test_name} - 通过")
                print(f"📝 消息: {result.get('message', '成功')}")
                self.passed += 1
                
                # 显示关键结果
                if "text" in result and result["text"]:
                    text_preview = result["text"][:100] + "..." if len(result["text"]) > 100 else result["text"]
                    print(f"📄 文本预览: {text_preview}")
                    print(f"📊 文本长度: {result.get('length', 0)}")
                    
                if "file_info" in result:
                    file_info = result["file_info"]
                    print(f"📁 文件信息: {file_info.get('file_extension', 'unknown')} - {file_info.get('file_size_mb', 0):.2f}MB")
                    
                if "processing_time" in result.get("extraction_info", {}):
                    print(f"⏱️ 处理时间: {result['extraction_info']['processing_time']:.2f}秒")
                
            else:
                print(f"❌ {test_name} - 失败")
                message = result.get('message', '未知错误') if isinstance(result, dict) else str(result)
                print(f"💬 错误: {message}")
                self.failed += 1
                
            self.test_results.append({
                "name": test_name,
                "status": "success" if (isinstance(result, dict) and result.get("status") == "success") else "failed",
                "result": result
            })
            
        except Exception as e:
            print(f"💥 {test_name} - 异常: {str(e)}")
            self.failed += 1
            self.test_results.append({
                "name": test_name,
                "status": "error",
                "result": {"message": f"测试异常: {str(e)}"}
            })
    
    async def test_basic_file_parsing(self):
        """测试基础文件解析功能"""
        print("\n📄 === 基础文件解析测试 ===")
        
        test_files = self.setup_test_files()
        
        # 测试文本文件
        await self.run_test(
            "文本文件解析",
            extract_text_from_file,
            input_file_path=test_files['txt'],
            max_length=1000
        )
        
        # 测试JSON文件
        await self.run_test(
            "JSON文件解析",
            extract_text_from_file,
            input_file_path=test_files['json'],
            max_length=1000
        )
        
        # 测试CSV文件
        await self.run_test(
            "CSV文件解析",
            extract_text_from_file,
            input_file_path=test_files['csv'],
            max_length=1000
        )
        
        # 测试Markdown文件
        await self.run_test(
            "Markdown文件解析",
            extract_text_from_file,
            input_file_path=test_files['md'],
            max_length=1000
        )
        
        # 测试HTML文件
        await self.run_test(
            "HTML文件解析",
            extract_text_from_file,
            input_file_path=test_files['html'],
            max_length=1000
        )
    
    async def test_advanced_features(self):
        """测试高级功能"""
        print("\n🚀 === 高级功能测试 ===")
        
        test_files = self.setup_test_files()
        
        # 测试包含元数据
        await self.run_test(
            "包含元数据解析",
            extract_text_from_file,
            input_file_path=test_files['txt'],
            include_metadata=True
        )
        
        # 测试文本截取
        await self.run_test(
            "文本截取功能",
            extract_text_from_file,
            input_file_path=test_files['txt'],
            start_index=5,
            max_length=20
        )
        
        # 测试批量处理
        file_list = [test_files['txt'], test_files['json'], test_files['csv']]
        await self.run_test(
            "批量文件处理",
            batch_extract_text,
            file_paths=file_list,
            max_length=500
        )
    
    async def test_url_parsing(self):
        """测试URL解析功能"""
        print("\n🌐 === URL解析测试 ===")
        
        # 测试简单网页解析（使用httpbin.org作为测试）
        test_urls = [
            "https://httpbin.org/html",  # 简单HTML页面
            "https://httpbin.org/json",  # JSON响应
        ]
        
        for url in test_urls:
            await self.run_test(
                f"URL解析 - {url}",
                extract_text_from_url,
                url=url,
                max_length=1000,
                timeout=10
            )
    
    async def test_file_validation(self):
        """测试文件验证功能"""
        print("\n🔍 === 文件验证测试 ===")
        
        test_files = self.setup_test_files()
        
        # 测试有效文件验证
        await self.run_test(
            "有效文件验证",
            validate_file_format,
            file_path=test_files['txt']
        )
        
        # 测试无效文件验证
        await self.run_test(
            "无效文件验证",
            validate_file_format,
            file_path="/nonexistent/file.txt"
        )
    
    async def test_supported_formats(self):
        """测试支持格式查询"""
        print("\n📋 === 支持格式测试 ===")
        
        await self.run_test(
            "获取支持格式",
            get_supported_formats
        )
    
    async def test_error_handling(self):
        """测试错误处理"""
        print("\n⚠️ === 错误处理测试 ===")
        
        # 测试不存在的文件
        await self.run_test(
            "不存在文件处理",
            extract_text_from_file,
            input_file_path="/path/does/not/exist.txt"
        )
        
        # 测试无效URL
        await self.run_test(
            "无效URL处理",
            extract_text_from_url,
            url="invalid-url"
        )
        
        # 测试超时URL
        await self.run_test(
            "URL超时处理",
            extract_text_from_url,
            url="https://httpbin.org/delay/5",
            timeout=2
        )
    
    async def test_performance(self):
        """测试性能"""
        print("\n⚡ === 性能测试 ===")
        
        test_files = self.setup_test_files()
        
        # 创建大文本文件
        large_txt = os.path.join(self.temp_dir, "large.txt")
        with open(large_txt, 'w', encoding='utf-8') as f:
            for i in range(1000):
                f.write(f"这是第{i+1}行文本内容，用于测试大文件处理性能。\n")
        
        start_time = time.time()
        result = await extract_text_from_file(
            input_file_path=large_txt,
            max_length=10000
        )
        end_time = time.time()
        
        if result.get("status") == "success":
            print(f"✅ 大文件性能测试 - 通过")
            print(f"📊 文件大小: {len(result['text'])} 字符")
            print(f"⏱️ 处理时间: {end_time - start_time:.2f}秒")
            self.passed += 1
        else:
            print(f"❌ 大文件性能测试 - 失败")
            self.failed += 1
    
    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*70)
        print("🎯 文件解析器测试总结")
        print("="*70)
        print(f"✅ 通过: {self.passed}")
        print(f"❌ 失败: {self.failed}")
        print(f"📊 总计: {self.passed + self.failed}")
        
        if self.failed > 0:
            print(f"\n❌ 失败的测试:")
            for result in self.test_results:
                if result["status"] != "success":
                    message = result["result"].get("message", "未知错误")
                    print(f"   • {result['name']}: {message}")
        
        success_rate = (self.passed / (self.passed + self.failed)) * 100 if (self.passed + self.failed) > 0 else 0
        print(f"\n🎉 成功率: {success_rate:.1f}%")
        
        # 功能统计
        print(f"\n📋 功能测试统计:")
        categories = {
            "基础解析": ["文本文件解析", "JSON文件解析", "CSV文件解析", "Markdown文件解析", "HTML文件解析"],
            "高级功能": ["包含元数据解析", "文本截取功能", "批量文件处理"],
            "网络功能": ["URL解析"],
            "验证功能": ["有效文件验证", "获取支持格式"],
            "错误处理": ["不存在文件处理", "无效URL处理", "URL超时处理"],
            "性能测试": ["大文件性能测试"]
        }
        
        for category, tests in categories.items():
            passed_in_category = sum(1 for result in self.test_results 
                                   if result["name"] in tests and result["status"] == "success")
            total_in_category = len(tests)
            print(f"   • {category}: {passed_in_category}/{total_in_category}")

async def main():
    """主测试函数"""
    print("🚀 开始文件解析器测试")
    print("="*70)
    
    test_suite = FileParserTestSuite()
    
    try:
        # 运行所有测试
        await test_suite.test_basic_file_parsing()
        await test_suite.test_advanced_features()
        await test_suite.test_url_parsing()
        await test_suite.test_file_validation()
        await test_suite.test_supported_formats()
        await test_suite.test_error_handling()
        await test_suite.test_performance()
        
        # 打印测试总结
        test_suite.print_summary()
        
    finally:
        # 清理测试文件
        test_suite.cleanup_test_files()

if __name__ == "__main__":
    asyncio.run(main()) 