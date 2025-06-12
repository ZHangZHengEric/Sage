#!/usr/bin/env python3
"""
Execute Command MCP Server 使用示例

展示如何使用各种功能
"""

import asyncio
import json
from execute_command import (
    execute_shell_command,
    execute_python_code,
    check_command_availability
)

async def demo_shell_commands():
    """演示Shell命令执行"""
    print("🐚 Shell命令执行示例")
    print("="*40)
    
    # 基本命令执行
    print("1. 基本命令执行:")
    result = await execute_shell_command("echo 'Hello, MCP Server!'")
    print(f"   输出: {result['stdout'].strip()}")
    
    # 带工作目录的命令
    print("\n2. 指定工作目录:")
    result = await execute_shell_command("pwd", workdir="/tmp")
    print(f"   当前目录: {result['stdout'].strip()}")
    
    # 使用环境变量
    print("\n3. 使用环境变量:")
    result = await execute_shell_command(
        "echo '用户名: $USER, 测试变量: $TEST_VAR'",
        env_vars={"TEST_VAR": "这是测试值"}
    )
    print(f"   输出: {result['stdout'].strip()}")

async def demo_python_execution():
    """演示Python代码执行"""
    print("\n\n🐍 Python代码执行示例")
    print("="*40)
    
    # 简单Python代码
    print("1. 简单数学计算:")
    code = """
import math
result = math.pi * (5 ** 2)
print(f"圆面积 (半径=5): {result:.2f}")
"""
    result = await execute_python_code(code)
    print(f"   输出: {result['output'].strip()}")
    
    # 数据处理示例
    print("\n2. 数据处理:")
    code = """
data = [1, 2, 3, 4, 5]
squared = [x**2 for x in data]
print(f"原数据: {data}")
print(f"平方后: {squared}")
print(f"平均值: {sum(data)/len(data)}")
"""
    result = await execute_python_code(code)
    print(f"   输出:\n{result['output']}")

async def demo_command_check():
    """演示命令可用性检查"""
    print("\n\n🔍 命令可用性检查示例")
    print("="*40)
    
    commands_to_check = ["python", "git", "node", "docker", "kubectl"]
    result = await check_command_availability(commands_to_check)
    
    if result["success"]:
        print("可用的命令:")
        for cmd in result["available_commands"]:
            path = result["command_paths"].get(cmd, "未知路径")
            print(f"  ✅ {cmd} -> {path}")
        
        if result["unavailable_commands"]:
            print("\n不可用的命令:")
            for cmd in result["unavailable_commands"]:
                print(f"  ❌ {cmd}")

async def demo_error_handling():
    """演示错误处理"""
    print("\n\n⚠️ 错误处理示例")
    print("="*40)
    
    # 尝试执行危险命令
    print("1. 尝试执行危险命令:")
    result = await execute_shell_command("rm -rf /important_file")
    print(f"   结果: {result.get('error', '未知错误')}")
    
    # 尝试执行不存在的命令
    print("\n2. 尝试执行不存在的命令:")
    result = await execute_shell_command("nonexistent_command_xyz")
    print(f"   结果: 命令执行失败")
    
    # Python语法错误
    print("\n3. Python语法错误:")
    result = await execute_python_code("print('hello world'")  # 缺少右括号
    print(f"   结果: 语法错误被正确捕获")

async def main():
    """主演示函数"""
    print("🚀 Execute Command MCP Server 功能演示")
    print("="*50)
    
    try:
        await demo_shell_commands()
        await demo_python_execution()
        await demo_command_check()
        await demo_error_handling()
        
        print("\n\n✨ 演示完成！")
        print("="*50)
        
    except Exception as e:
        print(f"❌ 演示过程中出现错误: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 