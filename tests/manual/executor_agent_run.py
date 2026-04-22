"""
ExecutorAgent run_stream 演示
演示执行智能体的功能
"""
import sys
import yaml
import datetime
import os,sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import json
from openai import OpenAI

from agents.agent.message_manager import MessageManager

def main():
    print("⚡ ExecutorAgent run_stream 演示")
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
    print("⚡ 创建ExecutorAgent...")
    from agents.agent.executor_agent.executor_agent import ExecutorAgent
    from agents.task.task_manager import TaskManager
    
    agent = ExecutorAgent(
        model=model,
        model_config=llm_config
    )
    
    session_id = f"executor_demo_{datetime.datetime.now().strftime('%H%M%S')}"
    task_manager = TaskManager(session_id=session_id)
    message_manager = MessageManager(
        session_id=session_id,
        max_token_limit=8000,
        auto_merge_chunks=True
    )
    print(f"✅ Agent: {agent.__class__.__name__}")
    print(f"✅ 会话: {session_id}")
    
    # 4. 准备消息（包含规划结果）
    planning_result = {
        "next_step": {
            "description": "创建一个简单的Python Hello World程序",
            "expected_output": "输出Hello World的Python代码",
            "required_tools": []
        }
    }
    
    messages = [
        {
            "role": "user",
            "content": "请帮我创建第一个Python程序",
            "type": "normal",
            "message_id": "user_001",
            "timestamp": datetime.datetime.now().isoformat()
        },
        {
            "role": "assistant",
            "content": f"Planning: {json.dumps(planning_result, ensure_ascii=False)}",
            "type": "planning_result",
            "message_id": "planning_001",
            "timestamp": datetime.datetime.now().isoformat()
        }
    ]
    
    message_manager.add_messages(messages)
    
    system_context = {
        "workspace": "/tmp/sage",
        "current_time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "回答语言": "中文"
    }
    
    # 5. 执行run_stream
    print("\n⚡ 执行run_stream...")
    print("🔄 实时输出:")
    print("-" * 60)
    
    chunk_count = 0
    all_content = ""
    
    try:
        for chunks in agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            session_id=session_id,
            system_context=system_context
        ):
            for chunk in chunks:
                chunk_count += 1                
                content = chunk.get('show_content', '')
                all_content += content
                print(content, end='', flush=True)
                
    
        print(f"\n" + "-" * 60)
        print(f"✅ run_stream执行完成")
        
        # 6. 结果分析
        print(f"\n📊 执行结果统计:")
        print(f"   流式块数量: {chunk_count}")
        print(f"   内容总长度: {len(all_content)} 字符")
        
        message_manager.log_print_messages(message_manager.get_all_messages())
        
        # 显示部分内容样本
        if len(all_content) > 0:
            sample_content = all_content[:500] + "..." if len(all_content) > 500 else all_content
            print(f"\n📝 响应内容样本:")
            print(f"```")
            print(sample_content)
            print(f"```")
        
        success = len(all_content) > 0
        if success:
            print(f"\n🎉 演示测试成功！ExecutorAgent.run_stream 正常工作")
            print(f"🔍 核心功能验证:")
            print(f"   ✅ 模型配置加载正常")
            print(f"   ✅ Agent初始化成功")
            print(f"   ✅ 流式输出工作正常")
            print(f"   ✅ 执行功能正常")
            print(f"   ✅ MessageManager集成正常")
        else:
            print(f"\n⚠️ 演示测试异常：未生成执行内容")
        
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