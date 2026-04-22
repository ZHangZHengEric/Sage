#!/usr/bin/env python3
"""
TaskAnalysisAgent 测试演示
真实调用大模型进行需求分析
"""
import sys
import yaml
import datetime
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from openai import OpenAI
from agents.agent.message_manager import MessageManager

def main():
    print("🎭 TaskAnalysisAgent 真实测试演示")
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
    print("🚀 创建TaskAnalysisAgent...")
    from agents.agent.task_analysis_agent.task_analysis_agent import TaskAnalysisAgent
    from agents.task.task_manager import TaskManager
    from agents.tool.tool_manager import ToolManager
    
    agent = TaskAnalysisAgent(
        model=model,
        model_config=llm_config,
        system_prefix='专业需求分析师'
    )
    
    session_id = f"analysis_demo_{datetime.datetime.now().strftime('%H%M%S')}"
    task_manager = TaskManager(session_id=session_id)
    tool_manager = ToolManager()
    message_manager = MessageManager(
        session_id=session_id,
        max_token_limit=8000,
        auto_merge_chunks=True
    )
    print(f"✅ Agent: {agent.agent_name}")
    print(f"✅ 会话: {session_id}")
    
    # 4. 准备用户需求消息
    messages = [
        {
            "role": "user",
            "content": '''我想开发一个个人博客网站，需要以下功能：
1. 用户注册和登录系统
2. 文章发布和编辑功能
3. 评论和回复系统
4. 标签和分类管理
5. 搜索功能
6. 响应式设计，支持移动端
7. SEO优化
8. 后台管理界面

技术要求：
- 使用Python Flask框架
- 数据库使用MySQL
- 前端使用Bootstrap和jQuery
- 部署到云服务器
- 预算控制在5000元以内
- 开发周期希望在2个月完成

请详细分析这个项目的技术难点、时间安排和资源需求。''',
            "type": "normal",
            "message_id": "user_analysis_001",
            "timestamp": datetime.datetime.now().isoformat()
        }
    ]
    
    message_manager.add_messages(messages)
    
    system_context = {
        "workspace": "/tmp/sage",
        "session_id": session_id,
        "user_preferences": {
            "language": "zh-CN",
            "analysis_depth": "comprehensive",
        }
    }
    
    print(f"\n📝 分析任务: 博客网站开发需求分析")
    
    # 5. 执行run_stream
    print("\n⚡ 执行需求分析...")
    print("🔄 实时输出:")
    print("-" * 60)
    
    chunk_count = 0
    
    try:
        # 执行流式分析
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
                
                if chunk_type == 'task_analysis_result':
                    content = chunk.get('content', '')
                    print(content, end='', flush=True)
                else:
                    # 其他类型的chunk
                    if chunk_count <= 10:  # 只显示前10个非主要chunk
                        print(f"\n[{chunk_type}]", end='')
    
        print(f"\n" + "-" * 60)
        print(f"✅ 需求分析执行完成")
        
        # 6. 结果统计
        all_messages = message_manager.get_all_messages()
        
        print(f"\n📊 执行结果统计:")
        print(f"   流式块数量: {chunk_count}")
        print(f"   消息总数: {len(all_messages)}")
        
        # 显示MessageManager中的最终消息
        analysis_messages = [msg for msg in all_messages if msg.get('role') == 'assistant']
        if analysis_messages:
            print(f"\n📨 Agent生成的消息数量: {len(analysis_messages)}")
            # for i, msg in enumerate(analysis_messages):
            #     content_preview = msg.get('content', '')[:100] + '...' if len(msg.get('content', '')) > 100 else msg.get('content', '')
            #     # print(f"   消息{i+1}: {msg}")
                # print(f"   消息{i+1}: {msg.get('type', 'unknown')} - {content_preview}")
        
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