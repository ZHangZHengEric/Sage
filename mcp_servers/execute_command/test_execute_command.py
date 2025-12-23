#!/usr/bin/env python3
"""
Execute Command MCP Server 测试套件

测试命令执行、Python代码运行、系统监控等功能
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from execute_command import (
    check_command_availability,
    execute_python_code,
    execute_shell_command,
    security_manager,
)


class ExecuteCommandTester:
    """命令执行测试器"""
    
    def __init__(self):
        self.test_results = []
        self.temp_dir = tempfile.mkdtemp()
    
    def log_test(self, test_name: str, success: bool, message: str = ""):
        """记录测试结果"""
        status = "✅ PASS" if success else "❌ FAIL"
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message
        })
        print(f"{status} {test_name}: {message}")
    
    async def test_security_manager(self):
        """测试安全管理器"""
        print("\n🔒 测试安全管理器...")
        
        # 测试安全命令
        safe, reason = security_manager.is_command_safe("ls -la")
        self.log_test("安全命令检查", safe, reason)
        
        # 测试危险命令
        safe, reason = security_manager.is_command_safe("rm -rf /")
        self.log_test("危险命令检查", not safe, reason)
        
        # 测试恶意模式
        safe, reason = security_manager.is_command_safe("echo 'test' && rm file")
        self.log_test("恶意模式检查", not safe, reason)
        
        # 测试空命令
        safe, reason = security_manager.is_command_safe("")
        self.log_test("空命令检查", not safe, reason)
    
    async def test_basic_shell_commands(self):
        """测试基本Shell命令"""
        print("\n🐚 测试Shell命令执行...")
        
        # 测试简单命令
        result = await execute_shell_command("echo 'Hello, World!'")
        success = result["success"] and "Hello, World!" in result["stdout"]
        self.log_test("基本echo命令", success, result.get("stdout", "").strip())
        
        # 测试工作目录
        result = await execute_shell_command("pwd", workdir=self.temp_dir)
        success = result["success"] and self.temp_dir in result["stdout"]
        self.log_test("工作目录测试", success, f"工作目录: {result.get('stdout', '').strip()}")
        
        # 测试环境变量
        result = await execute_shell_command(
            "echo $TEST_VAR",
            env_vars={"TEST_VAR": "test_value"}
        )
        success = result["success"] and "test_value" in result["stdout"]
        self.log_test("环境变量测试", success, result.get("stdout", "").strip())
        
        # 测试超时
        result = await execute_shell_command("sleep 2", timeout=1)
        success = not result["success"] and "超时" in result.get("error", "")
        self.log_test("超时控制测试", success, result.get("error", ""))
    
    async def test_python_code_execution(self):
        """测试Python代码执行"""
        print("\n🐍 测试Python代码执行...")
        
        # 测试简单Python代码
        code = "print('Hello from Python!')"
        result = await execute_python_code(code)
        success = result["success"] and "Hello from Python!" in result["stdout"]
        self.log_test("简单Python代码", success, result.get("stdout", "").strip())
        
        # 测试数学计算
        code = """
import math
result = math.sqrt(16)
print(f"Square root of 16 is {result}")
"""
        result = await execute_python_code(code)
        success = result["success"] and "4.0" in result["stdout"]
        self.log_test("数学计算", success, result.get("stdout", "").strip())
        
        # 测试文件操作
        code = f"""
import os
test_file = os.path.join('{self.temp_dir}', 'test.txt')
with open(test_file, 'w') as f:
    f.write('Test content')
print(f"File created: {{os.path.exists(test_file)}}")
"""
        result = await execute_python_code(code, workdir=self.temp_dir)
        success = result["success"] and "True" in result["stdout"]
        self.log_test("文件操作", success, result.get("stdout", "").strip())
        
        # 测试语法错误
        code = "print('Hello world'"  # 缺少右括号
        result = await execute_python_code(code)
        success = not result["success"] and result["stderr"]
        self.log_test("语法错误处理", success, "正确捕获语法错误")
    
    
    async def test_command_availability(self):
        """测试命令可用性检查"""
        print("\n🔍 测试命令可用性检查...")
        
        # 测试常见命令
        common_commands = ["python", "python3", "ls", "echo", "cat"]
        result = await check_command_availability(common_commands)
        
        success = result["success"]
        self.log_test("命令可用性检查", success, f"检查了{result.get('total_checked', 0)}个命令")
        
        if success:
            available = result.get("available_commands", [])
            unavailable = result.get("unavailable_commands", [])
            
            self.log_test("可用命令", len(available) > 0, f"可用: {', '.join(available)}")
            if unavailable:
                self.log_test("不可用命令", True, f"不可用: {', '.join(unavailable)}")
    
    async def test_error_handling(self):
        """测试错误处理"""
        print("\n⚠️ 测试错误处理...")
        
        # 测试不存在的命令
        result = await execute_shell_command("nonexistent_command_12345")
        success = not result["success"]
        self.log_test("不存在命令处理", success, "正确处理不存在的命令")
        
        # 测试不存在的工作目录
        result = await execute_shell_command("echo test", workdir="/nonexistent/directory")
        success = not result["success"] and "不存在" in result.get("error", "")
        self.log_test("不存在目录处理", success, "正确处理不存在的目录")
        
        # 测试危险命令
        result = await execute_shell_command("rm -rf /")
        success = not result["success"] and "安全检查失败" in result.get("error", "")
        self.log_test("危险命令阻止", success, "正确阻止危险命令")
    
    async def test_performance(self):
        """测试性能"""
        print("\n⚡ 测试性能...")
        
        import time
        
        # 测试命令执行时间
        start_time = time.time()
        result = await execute_shell_command("echo 'Performance test'")
        execution_time = time.time() - start_time
        
        success = result["success"] and execution_time < 5.0
        self.log_test("命令执行性能", success, f"执行时间: {execution_time:.3f}秒")
        
        # 测试并发执行
        tasks = []
        for i in range(5):
            task = execute_shell_command(f"echo 'Concurrent test {i}'")
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        concurrent_time = time.time() - start_time
        
        success = all(r["success"] for r in results) and concurrent_time < 10.0
        self.log_test("并发执行性能", success, f"5个并发任务用时: {concurrent_time:.3f}秒")
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始Execute Command MCP Server测试...")
        print(f"📁 临时目录: {self.temp_dir}")
        
        try:
            await self.test_security_manager()
            await self.test_basic_shell_commands()
            await self.test_python_code_execution()
            await self.test_command_availability()
            await self.test_error_handling()
            await self.test_performance()
            
        except Exception as e:
            self.log_test("测试执行", False, f"测试过程中出现异常: {str(e)}")
        
        finally:
            # 清理临时目录
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
                print(f"🗑️ 清理临时目录: {self.temp_dir}")
            except Exception:
                pass
        
        self.print_summary()
    
    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*50)
        print("📋 测试总结")
        print("="*50)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"总测试数: {total_tests}")
        print(f"通过: {passed_tests} ✅")
        print(f"失败: {failed_tests} ❌")
        print(f"成功率: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print("\n❌ 失败的测试:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['message']}")
        
        print("\n✨ 测试完成!")

async def main():
    """主函数"""
    tester = ExecuteCommandTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())