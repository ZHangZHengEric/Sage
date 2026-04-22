#!/usr/bin/env python3
"""
PlanningAgent 真实测试演示
真实调用大模型进行规划生成
"""
import sys
import yaml
import datetime
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from openai import OpenAI
from agents.agent.message_manager import MessageManager

def main():
    print("🎭 PlanningAgent 真实测试演示")
    print("=" * 60)
    
    # 1. 加载配置
    print("📋 加载配置...")
    with open('../examples/fastapi_react_demo/backend/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    model_config = config['model']
    print(f"✅ 模型: {model_config['model_name']}")
    
    # 2. 创建OpenAI客户端
    print("🤖 创建模型...")
    model = OpenAI(
        api_key=model_config['api_key'],
        base_url=model_config['base_url']
    )
    
    llm_config = {
        "model": model_config['model_name'],
        "temperature": model_config.get('temperature', 0.2),
        "max_tokens": model_config.get('max_tokens', 4096)
    }
    print(f"✅ 模型初始化完成")
    
    # 3. 创建Agent
    print("🚀 创建PlanningAgent...")
    from agents.agent.planning_agent.planning_agent import PlanningAgent
    from agents.task.task_manager import TaskManager
    from agents.tool.tool_manager import ToolManager
    
    agent = PlanningAgent(
        model=model,
        model_config=llm_config,
        system_prefix='智能规划助手'
    )
    
    session_id = f"planning_demo_{datetime.datetime.now().strftime('%H%M%S')}"
    task_manager = TaskManager(session_id=session_id)
    tool_manager = ToolManager()
    message_manager = MessageManager(
        session_id=session_id,
        max_token_limit=8000,
        auto_merge_chunks=True
    )
    print(f"✅ Agent: {agent.__class__.__name__}")
    print(f"✅ 会话: {session_id}")
    
    # 4. 准备用户需求消息
    messages = [
        {
            "role": "user",
            "content": '''我想在接下来的6个月内转行成为一名AI工程师，目前我有以下背景：
- 计算机科学本科毕业
- 有2年Java后端开发经验
- 对机器学习有基础了解，但缺乏实战经验
- 英语水平良好，可以阅读英文技术文档
- 每天可以投入3-4小时学习时间
- 希望能够找到年薪30万以上的AI相关工作

学习目标：
1. 掌握Python和相关AI开发工具
2. 深入理解机器学习和深度学习理论
3. 具备实际项目开发能力
4. 了解AI行业发展趋势和就业机会
5. 建立个人作品集和技术影响力

请为我制定一个详细的6个月学习和转行计划，包括：
- 具体的学习路径和时间安排
- 推荐的学习资源和项目
- 技能提升的里程碑
- 求职准备和投递策略
- 风险控制和备选方案''',
            "type": "normal",
            "message_id": "user_planning_001",
            "timestamp": datetime.datetime.now().isoformat()
        }
    ]
    
    message_manager.add_messages(messages)
    
    system_context = {
        "workspace": "/tmp/sage",
        "session_id": session_id,
        "user_preferences": {
            "language": "zh-CN",
            "planning_depth": "comprehensive",
        }
    }
    
    print(f"\n📝 规划任务: AI工程师转行规划制定")
    
    # 5. 执行run_stream
    print("\n⚡ 执行规划生成...")
    print("🔄 实时输出:")
    print("-" * 60)
    
    chunk_count = 0
    
    try:
        # 执行流式规划
        for chunks in agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            for chunk in chunks:
                chunk_count += 1
                chunk_type = chunk.get('type', 'unknown')
                
                if chunk_type == 'planning_result':
                    content = chunk.get('show_content', '')
                    print(content, end='', flush=True)
                else:
                    # 其他类型的chunk
                    if chunk_count <= 10:  # 只显示前10个非主要chunk
                        print(f"\n[{chunk_type}]", end='')
    
        print(f"\n" + "-" * 60)
        print(f"✅ 规划生成执行完成")
        all_messages = message_manager.get_all_messages()
        message_manager.log_print_messages(all_messages)
        
        # 6. 结果统计
        print(f"\n📊 执行结果统计:")
        print(f"   流式块数量: {chunk_count}")
        print(f"   消息总数: {len(all_messages)}")
        
        # 显示MessageManager中的最终消息
        planning_messages = [msg for msg in all_messages if msg.get('role') == 'assistant']
        if planning_messages:
            print(f"\n📨 Agent生成的消息数量: {len(planning_messages)}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = main()
        print(f"\n{'🎊 演示完成！' if success else '💥 演示失败！'}")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n⏹️ 用户中断演示")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 演示程序异常: {e}")
        sys.exit(1) 