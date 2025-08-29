"""记忆管理系统测试

用于测试和验证记忆管理系统的功能。

Author: Eric ZZ
Date: 2024-12-21
"""

import os
import tempfile
import shutil
from pathlib import Path

from .memory_manager import UserMemoryManager
from .memory_types import MemoryType, MemoryBackend
from .memory_tools import MemoryTools, create_memory_tools_for_agent


def test_basic_memory_operations():
    """测试基础记忆操作"""
    print("=== 测试基础记忆操作 ===")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 初始化记忆管理器
        memory_manager = UserMemoryManager(
            user_id="test_user",
            memory_root=temp_dir,
            backend=MemoryBackend.LOCAL_FILE
        )
        
        # 测试偏好设置
        print("1. 测试偏好设置...")
        memory_manager.set_preference("language", "zh-CN")
        memory_manager.set_preference("response_style", "详细")
        
        # 测试偏好获取
        language = memory_manager.get_preference("language")
        style = memory_manager.get_preference("response_style")
        print(f"   语言偏好: {language}")
        print(f"   回复风格: {style}")
        
        # 测试添加经验
        print("2. 测试添加经验...")
        memory_manager.add_memory(
            content="Docker容器启动失败的解决方案：检查端口占用，重启Docker服务",
            memory_type=MemoryType.EXPERIENCE,
            tags=["docker", "故障排除"],
            importance=0.8
        )
        
        memory_manager.add_memory(
            content="Python导入错误解决：检查PYTHONPATH环境变量",
            memory_type=MemoryType.EXPERIENCE,
            tags=["python", "导入错误"],
            importance=0.7
        )
        
        # 测试搜索记忆
        print("3. 测试搜索记忆...")
        docker_memories = memory_manager.search_memories("docker")
        print(f"   找到 {len(docker_memories)} 条Docker相关记忆")
        for memory in docker_memories:
            print(f"   - {memory['content'][:50]}...")
        
        # 测试获取统计信息
        print("4. 测试统计信息...")
        stats = memory_manager.get_memory_stats()
        print(f"   总记忆数量: {stats['total_memories']}")
        print(f"   按类型分布: {stats['by_type']}")
        
        print("✅ 基础记忆操作测试通过")
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def test_memory_tools():
    """测试记忆工具"""
    print("\n=== 测试记忆工具 ===")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 初始化记忆管理器
        memory_manager = UserMemoryManager(
            user_id="test_user_tools",
            memory_root=temp_dir,
            backend=MemoryBackend.LOCAL_FILE
        )
        
        # 创建记忆工具
        memory_tools = MemoryTools(memory_manager)
        
        # 测试记住用户偏好
        print("1. 测试记住用户偏好...")
        result = memory_tools.remember_user_preference(
            "coding_style", "函数式", "用户偏好函数式编程风格"
        )
        print(f"   结果: {result}")
        
        # 测试保存解决方案
        print("2. 测试保存解决方案...")
        result = memory_tools.save_solution(
            "React组件渲染慢",
            "使用React.memo和useMemo优化渲染性能",
            ["react", "性能优化"],
            0.9
        )
        print(f"   结果: {result}")
        
        # 测试回忆相似经验
        print("3. 测试回忆相似经验...")
        result = memory_tools.recall_similar_experience("React性能问题")
        print(f"   结果: {result}")
        
        # 测试记录用户上下文
        print("4. 测试记录用户上下文...")
        result = memory_tools.note_user_context(
            "current_project", "正在开发一个React电商网站"
        )
        print(f"   结果: {result}")
        
        # 测试获取用户偏好
        print("5. 测试获取用户偏好...")
        result = memory_tools.get_user_preference("coding_style")
        print(f"   结果: {result}")
        
        # 测试获取记忆摘要
        print("6. 测试获取记忆摘要...")
        result = memory_tools.get_memory_summary()
        print(f"   结果: {result}")
        
        print("✅ 记忆工具测试通过")
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def test_agent_integration():
    """测试Agent集成"""
    print("\n=== 测试Agent集成 ===")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 初始化记忆管理器
        memory_manager = UserMemoryManager(
            user_id="test_agent",
            memory_root=temp_dir,
            backend=MemoryBackend.LOCAL_FILE
        )
        
        # 创建Agent工具字典
        agent_tools = create_memory_tools_for_agent(memory_manager)
        
        print(f"1. 可用工具数量: {len(agent_tools)}")
        print(f"2. 工具列表: {list(agent_tools.keys())}")
        
        # 模拟Agent使用工具
        print("3. 模拟Agent使用记忆工具...")
        
        # Agent记录用户偏好
        result = agent_tools["remember_user_preference"](
            "deployment_preference", "docker", "用户偏好使用Docker部署"
        )
        print(f"   记录偏好: {result}")
        
        # Agent保存解决方案
        result = agent_tools["save_solution"](
            "Docker容器无法访问",
            "检查防火墙设置和端口映射配置",
            ["docker", "网络", "故障排除"]
        )
        print(f"   保存方案: {result}")
        
        # Agent搜索相关经验
        result = agent_tools["recall_similar_experience"]("Docker问题")
        print(f"   搜索经验: {result}")
        
        print("✅ Agent集成测试通过")
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def run_all_tests():
    """运行所有测试"""
    print("开始记忆管理系统测试...\n")
    
    try:
        test_basic_memory_operations()
        test_memory_tools()
        test_agent_integration()
        
        print("\n🎉 所有测试通过！记忆管理系统工作正常。")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()