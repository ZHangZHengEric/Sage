"""
TaskDecomposeAgent run_stream 最终演示
修正了generator/async generator的问题
"""
import sys
import yaml
import datetime
import os,sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from openai import OpenAI
from agents.agent.message_manager import MessageManager
def main():
    print("🎭 TaskDecomposeAgent run_stream 最终演示")
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
    print("🚀 创建TaskDecomposeAgent...")
    from agents.agent.task_decompose_agent.task_decompose_agent import TaskDecomposeAgent
    from agents.task.task_manager import TaskManager
    
    agent = TaskDecomposeAgent(
        model=model,
        model_config=llm_config
    )
    
    session_id = f"demo_{datetime.datetime.now().strftime('%H%M%S')}"
    task_manager = TaskManager(session_id=session_id)
    message_manager = MessageManager(
        session_id=session_id,
        max_token_limit=8000,
        auto_merge_chunks=True
    )
    print(f"✅ Agent: {agent.agent_name}")
    print(f"✅ 会话: {session_id}")
    
    # 4. 准备消息
    messages = [
        {
            "role": "user",
            "content": "请帮我制定一个2个月的Python学习计划。我是编程初学者，希望掌握Python基础语法、面向对象编程，并完成一个小项目。",
            "type": "normal",
            "message_id": "user_001",
            "timestamp": datetime.datetime.now().isoformat()
        }
    ]
    
    message_manager.add_messages(messages)
    
    system_context = {
        "workspace": "/tmp/sage",
    }
    MessageManager()
    print(f"\n📝 任务描述: Python学习计划制定")
    
    # 5. 执行run_stream (使用普通for循环，不是async for)
    print("\n⚡ 执行run_stream...")
    print("🔄 实时输出:")
    print("-" * 60)
    
    chunk_count = 0
    all_content = ""
    
    try:
        # 注意：这里使用普通的for循环，因为run_stream返回的是generator，不是async generator
        for chunks in agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            session_id=session_id,
            system_context=system_context
        ):
            for chunk in chunks:
                chunk_count += 1
                chunk_type = chunk.get('type', 'unknown')
                
                if chunk_type == 'task_decomposition':
                    content = chunk.get('content', '')
                    all_content += content
                    print(content, end='', flush=True)
                else:
                    # 其他类型的chunk，简化显示
                    if chunk_count <= 10:  # 只显示前10个非主要chunk
                        print(f"\n[{chunk_type}]", end='')
    
        print(f"\n" + "-" * 60)
        print(f"✅ run_stream执行完成")
        all_messages = message_manager.get_all_messages()
        message_manager.log_print_messages(all_messages)

        
        # 6. 结果分析
        all_tasks = task_manager.get_all_tasks()
        
        print(f"\n📊 执行结果统计:")
        print(f"   流式块数量: {chunk_count}")
        print(f"   最终任务数: {len(all_tasks)}")
        print(f"   内容总长度: {len(all_content)} 字符")
        
        # 显示最终任务列表
        if len(all_tasks) > 0:
            print(f"\n📋 最终生成的任务列表:")
            for i, task in enumerate(all_tasks, 1):
                print(f"   {i}. {task.description}")
                print(f"      - ID: {task.task_id}")
                print(f"      - 优先级: {task.priority.value}")
                print(f"      - 状态: {task.status.value}")
                if task.dependencies:
                    print(f"      - 依赖: {', '.join(task.dependencies)}")
                print()
        else:
            print(f"\n⚠️ 警告: 未生成任何任务")
        
        # 显示部分内容样本
        if len(all_content) > 0:
            sample_content = all_content[:500] + "..." if len(all_content) > 500 else all_content
            print(f"\n📝 响应内容样本:")
            print(f"```")
            print(sample_content)
            print(f"```")
        
        success = len(all_tasks) > 0
        if success:
            print(f"\n🎉 演示测试成功！TaskDecomposeAgent.run_stream 正常工作")
            print(f"🔍 核心功能验证:")
            print(f"   ✅ 模型配置加载正常")
            print(f"   ✅ Agent初始化成功")
            print(f"   ✅ 流式输出工作正常")
            print(f"   ✅ 任务分解功能正常")
            print(f"   ✅ TaskManager集成正常")
        else:
            print(f"\n⚠️ 演示测试异常：未生成任务")
        
        return success
        
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
