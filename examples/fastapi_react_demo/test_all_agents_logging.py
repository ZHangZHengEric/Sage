"""
测试所有智能体的LLM请求记录功能

验证PlanningAgent、ObservationAgent、TaskDecomposeAgent和ExecutorAgent
的LLM请求都被正确记录到文件中。
"""

import sys
import os
from pathlib import Path
import json
import tempfile
import shutil
import uuid

# 添加项目根目录到Python路径
sys.path.insert(0, "/srv/Sage")

from sagents.utils.llm_request_logger import get_llm_logger, cleanup_logger

def test_all_agents_logging():
    """测试所有智能体的LLM请求记录"""
    
    print("🚀 开始测试所有智能体的LLM请求记录功能")
    print("=" * 60)
    
    # 创建测试目录
    test_workspace = tempfile.mkdtemp(prefix="test_all_agents_")
    session_id = f"all_agents_{uuid.uuid4().hex[:8]}"
    
    try:
        print(f"📂 测试工作空间: {test_workspace}")
        print(f"🆔 测试会话ID: {session_id}")
        
        # 1. 初始化记录器
        print("\n1. 初始化LLM记录器")
        llm_logger = get_llm_logger(session_id)
        print("   ✅ 记录器初始化完成")
        
        # 2. 模拟不同智能体的请求（按实际调用方式）
        print("\n2. 模拟不同智能体的LLM请求")
        
        # 模拟PlanningAgent的请求（step_name="planning"）
        planning_request_id = llm_logger.log_request(
            agent_name="PlanningAgent",
            step_name="planning",
            messages=[
                {"role": "system", "content": "你是一个任务规划智能体"},
                {"role": "user", "content": "请为我制定学习计划"}
            ],
            model_config={"model": "gpt-4", "temperature": 0.7}
        )
        print(f"   📄 已记录PlanningAgent请求: {planning_request_id}")
        
        # 模拟ObservationAgent的请求（step_name="observation"）
        observation_request_id = llm_logger.log_request(
            agent_name="ObservationAgent",
            step_name="observation", 
            messages=[
                {"role": "system", "content": "你是一个任务观察智能体"},
                {"role": "user", "content": "请观察当前任务执行状态"}
            ],
            model_config={"model": "gpt-4", "temperature": 0.3}
        )
        print(f"   📄 已记录ObservationAgent请求: {observation_request_id}")
        
        # 模拟TaskDecomposeAgent的请求（step_name="task_decompose"）
        decompose_request_id = llm_logger.log_request(
            agent_name="TaskDecomposeAgent",
            step_name="task_decompose",
            messages=[
                {"role": "system", "content": "你是一个任务分解智能体"},
                {"role": "user", "content": "请将复杂任务分解为子任务"}
            ],
            model_config={"model": "gpt-4", "temperature": 0.5}
        )
        print(f"   📄 已记录TaskDecomposeAgent请求: {decompose_request_id}")
        
        # 模拟ExecutorAgent的请求（step_name="llm_call"）
        executor_request_id = llm_logger.log_request(
            agent_name="ExecutorAgent", 
            step_name="llm_call",
            messages=[
                {"role": "system", "content": "你是一个任务执行智能体"},
                {"role": "user", "content": "请执行文件操作任务"}
            ],
            model_config={"model": "gpt-4", "temperature": 0.1}
        )
        print(f"   📄 已记录ExecutorAgent请求: {executor_request_id}")
        
        print("   ✅ 所有智能体请求记录完成")
        
        # 3. 验证文件生成
        print("\n3. 验证文件生成")
        requests_dir = Path(test_workspace) / session_id / "llm_requests"
        
        print(f"   📁 请求目录: {requests_dir}")
        print("   📂 生成的文件:")
        
        all_files = list(requests_dir.glob("*.json"))
        for file_path in sorted(all_files):
            print(f"      {file_path.name}")
        
        # 验证文件数量
        assert len(all_files) == 4, f"应该有4个JSON文件，实际有{len(all_files)}个"
        print("   ✅ 文件数量正确")
        
        # 4. 验证文件命名格式
        print("\n4. 验证文件命名格式")
        
        expected_agents = ["PlanningAgent", "ObservationAgent", "TaskDecomposeAgent", "ExecutorAgent"]
        found_agents = set()
        
        for file_path in all_files:
            filename = file_path.name
            
            # 检查文件名是否以期望的智能体名称开头
            agent_found = False
            for agent_name in expected_agents:
                if filename.startswith(f"{agent_name}_"):
                    found_agents.add(agent_name)
                    agent_found = True
                    print(f"   ✅ {filename} - 格式正确 ({agent_name})")
                    break
            
            assert agent_found, f"文件名格式不正确: {filename}"
        
        # 验证所有智能体都有文件
        assert found_agents == set(expected_agents), f"缺少智能体文件: {set(expected_agents) - found_agents}"
        print("   ✅ 所有智能体都有对应的请求文件")
        
        # 5. 验证文件内容
        print("\n5. 验证文件内容")
        
        for file_path in all_files:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 验证必要字段
            required_fields = [
                "request_id", "session_id", "agent_name", "step_name", 
                "timestamp", "request_counter", "messages", "model_config"
            ]
            
            for field in required_fields:
                assert field in data, f"文件 {file_path.name} 缺少字段: {field}"
            
            # 验证session_id正确
            assert data["session_id"] == session_id, f"会话ID不匹配: {data['session_id']}"
            
            # 验证agent_name和step_name组合正确
            agent_name = data["agent_name"]
            step_name = data["step_name"]
            
            expected_steps = {
                "PlanningAgent": "planning",
                "ObservationAgent": "observation", 
                "TaskDecomposeAgent": "task_decompose",
                "ExecutorAgent": "llm_call"
            }
            
            if agent_name in expected_steps:
                assert step_name == expected_steps[agent_name], \
                    f"{agent_name} 的 step_name 应该是 {expected_steps[agent_name]}，实际是 {step_name}"
            
            print(f"   ✅ {file_path.name} - 内容验证通过 ({agent_name}-{step_name})")
        
        # 6. 测试list_request_files功能
        print("\n6. 测试文件列表功能")
        
        request_files = llm_logger.list_request_files()
        assert len(request_files) == 4, f"应该返回4个文件信息，实际返回{len(request_files)}个"
        
        print(f"   📊 返回了 {len(request_files)} 个文件信息")
        
        # 按智能体类型分组统计
        agent_stats = {}
        for file_info in request_files:
            agent_name = file_info['agent_name']
            step_name = file_info['step_name']
            
            if agent_name not in agent_stats:
                agent_stats[agent_name] = []
            agent_stats[agent_name].append(step_name)
            
            print(f"   📄 {file_info['filename']} ({agent_name}-{step_name})")
        
        print("   ✅ 文件列表功能验证通过")
        
        # 7. 验证智能体统计
        print("\n7. 验证智能体统计")
        
        print("   📊 智能体请求统计:")
        for agent_name, steps in agent_stats.items():
            print(f"      {agent_name}: {len(steps)} 个请求 (步骤: {', '.join(steps)})")
        
        # 验证每个智能体都有且仅有一个请求
        for agent_name in expected_agents:
            assert agent_name in agent_stats, f"缺少 {agent_name} 的请求记录"
            assert len(agent_stats[agent_name]) == 1, f"{agent_name} 应该只有1个请求，实际有{len(agent_stats[agent_name])}个"
        
        print("   ✅ 智能体统计正确")
        
        # 8. 清理测试
        print("\n8. 清理记录器")
        cleanup_logger(session_id)
        print("   ✅ 记录器清理完成")
        
        print("\n🎉 所有测试通过！")
        print("=" * 60)
        print("📝 验证结果:")
        print("   • PlanningAgent 请求被正确记录 (step_name: planning)")
        print("   • ObservationAgent 请求被正确记录 (step_name: observation)")
        print("   • TaskDecomposeAgent 请求被正确记录 (step_name: task_decompose)")
        print("   • ExecutorAgent 请求被正确记录 (step_name: llm_call)")
        print("   • 文件名格式: {AgentName}_{RequestID}.json")
        print("   • 所有session_id参数都正确传递")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # 清理测试目录
        try:
            shutil.rmtree(test_workspace)
            print(f"\n🗑️  已清理测试目录: {test_workspace}")
        except Exception as e:
            print(f"⚠️  清理测试目录失败: {e}")

if __name__ == "__main__":
    success = test_all_agents_logging()
    
    if success:
        print("\n✅ 所有智能体LLM请求记录功能测试完成！")
        print("现在PlanningAgent、ObservationAgent、TaskDecomposeAgent和ExecutorAgent")
        print("的所有LLM请求都会被正确记录。")
    else:
        print("\n❌ 测试失败！请检查错误信息")
        sys.exit(1) 