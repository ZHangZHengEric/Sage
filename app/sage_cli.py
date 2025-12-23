import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from copy import deepcopy
from typing import Any, Dict, Union

from openai import AsyncOpenAI
from rich.console import Console

from sagents.context.messages.message import MessageChunk, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.sagents import SAgent
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.logger import logger
from sagents.utils.streaming_message_box import (
    StreamingMessageBox,
    display_items_in_columns,
)

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
print(f'添加路径：{os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))}')


# 导入流式消息框工具

def display_tools(console, tool_manager: Union[ToolManager, ToolProxy]):
    try:
        if hasattr(tool_manager, 'list_tools_simplified'):
            available_tools = tool_manager.list_tools_simplified()
        elif hasattr(tool_manager, 'tool_manager') and hasattr(tool_manager.tool_manager, 'list_tools_simplified'):
            available_tools = tool_manager.tool_manager.list_tools_simplified()
        else:
            available_tools = []

        if available_tools:
            tool_names = [tool.get('name', '未知工具') for tool in available_tools]
            # 排序
            tool_names.sort()
            display_items_in_columns(tool_names, title="可用工具列表", color="cyan")
        else:
            console.print("[yellow]未检测到可用工具。[/yellow]")
    except Exception as e:
        logger.error(f"获取工具列表时出错: {traceback.format_exc()}")
        console.print(f"\n[red]获取工具列表时出错: {e}[/red]")


async def chat(agent: SAgent, tool_manager: Union[ToolManager, ToolProxy]):
    # 对话式的，流式的打印只显示 show_content 的信息到命令行，且命令行的样式要好看一些，调用agent 进行对话

    console = Console()

    # 在chat函数中调用display_tools
    display_tools(console, tool_manager)

    console.print("[green]欢迎使用 SAgent CLI。输入 'exit' 或 'quit' 退出。[/green]")
    # 打印当前的session id

    # 时间月日时分+4位随机数
    session_id = time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime()) + '_'+str(uuid.uuid4())[:4]
    console.print(f"[dim]当前session id: {session_id}[/dim]")

    messages = []
    while True:
        try:
            user_input = console.input("[bold blue]你: [/bold blue]")
            if user_input.lower() in ['exit', 'quit']:
                console.print("[green]再见！[/green]")
                break

            console.print("[magenta]SAgent:[/magenta]")
            last_message_id = None
            messages.append(MessageChunk(role='user', content=user_input, type=MessageType.NORMAL.value))
            all_chunks = []
            current_message_box = None

            async for chunks in agent.run_stream(input_messages=messages,
                                                 tool_manager=tool_manager,
                                                 session_id=session_id,
                                                 user_id=config['user_id'],
                                                 deep_thinking=config['use_deepthink'],
                                                 multi_agent=config['use_multi_agent'],
                                                 available_workflows=config['available_workflows'],
                                                 system_context=config['system_context']
                                                 ):
                for chunk in chunks:
                    if isinstance(chunk, MessageChunk):
                        all_chunks.append(deepcopy(chunk))
                        try:
                            if chunk.message_id != last_message_id:
                                # 如果有之前的消息框，先完成它
                                if current_message_box is not None:
                                    current_message_box.finish()

                                # 创建新的消息框
                                if chunk.show_content and chunk.type:
                                    message_type = chunk.type or chunk.message_type or 'normal'
                                    current_message_box = StreamingMessageBox(console, message_type)

                                last_message_id = chunk.message_id
                        except Exception:
                            print(chunk)

                        if chunk.show_content and current_message_box:
                            # 确保 show_content 是字符串，避免 'str' object has no attribute 'invalidation_hash' 错误
                            content_to_print = str(chunk.show_content)
                            # 使用改进的流式输出方法，显示增量的内容，content_to_print就是增量的内容
                            for char in content_to_print:
                                current_message_box.add_content(char)

            # 完成最后一个消息框
            if current_message_box is not None:
                current_message_box.finish()

            console.print("")  # 确保最后有一个换行
            # print(f"before messages: {messages}")
            # print(f"all_chunks: {all_chunks}")
            messages = MessageManager.merge_new_messages_to_old_messages(all_chunks, messages)
            # print(f"after messages: {messages}")
        except KeyboardInterrupt:
            console.print("[green]再见！[/green]")
            break
        except EOFError:
            console.print("[green]再见！[/green]")
            break
        except Exception as e:
            console.print(f"[red]发生错误: {e}[/red]")
            traceback.print_exc()
            exit(0)


def parse_arguments() -> Dict[str, Any]:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Sage Multi-Agent CLI Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python sagents_cli.py --api_key YOUR_API_KEY --model gpt-4
  python sagents_cli.py --api_key YOUR_API_KEY --model gpt-4 --query "帮我分析一下数据"
        """
    )

    parser.add_argument('--api_key', required=True,
                        help='OpenRouter API key（必需）')
    parser.add_argument('--model', required=True,
                        help='模型名称')
    parser.add_argument('--base_url', required=True,
                        help='API base URL')
    parser.add_argument('--user_id', type=str, default=None,
                        help='用户ID')
    parser.add_argument('--memory_root', type=str, default=None,
                        help='记忆根目录')
    parser.add_argument('--tools_folders', nargs='+', default=[],
                        help='工具目录路径（多个路径用空格分隔）')
    parser.add_argument('--max_tokens', type=int, default=4096,
                        help='最大令牌数')
    parser.add_argument('--temperature', type=float, default=0.2,
                        help='温度参数')
    parser.add_argument('--no-deepthink', action='store_true', default=None,
                        help='禁用深度思考')
    parser.add_argument('--no-multi-agent', action='store_true', default=None,
                        help='禁用多智能体推理')
    parser.add_argument('--workspace', type=str, default=os.path.join(os.getcwd(), 'agent_workspace'),
                        help='工作目录')
    parser.add_argument('--mcp_setting_path', type=str, default=os.path.join(os.path.dirname(__file__), 'mcp_setting.json'),
                        help="""MCP 设置文件路径，文件内容为json格式，示例：
{
    "mcpServers": {
        "auth_sse_mcp_server": {
            "sse_url": "http://127.0.0.1:20042/sse",
            "disabled": false,
            "api_key": "sk-0r4Y-8eAeRXeA-9TpQdoxoHCDsdLpY5VVG2mJHpuzaVvc"
        },
        "sse_mcp_server": {
            "sse_url": "http://127.0.0.1:14343/sse",
            "disabled": true
        },
        "streamable_mcp_server": {
            "streamablehhtp_url": "http://127.0.0.1:14348/mcp",
            "disabled": true
        },
        "filesystem": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", "/path/to/workspace"],
            "env": {}
        }
    }
}
""")
    parser.add_argument('--preset_running_agent_config_path', type=str, default=os.path.join(os.path.dirname(__file__), 'preset_running_agent_config.json'),
                        help="""预设运行配置文件路径，文件内容为json格式，示例：
{{
  "systemPrefix": "你是一个智能助手，你可以帮助用户解决问题",
  "deepThinking": false,
  "multiAgent": false,
  "moreSupport": false,
  "maxLoopCount": 10,
  "llmConfig": {{
    "model": "",
    "maxTokens": "",
    "temperature": ""
  }},
  "availableTools": [
    "complete_task",
    "calculate",
    "file_read",
    "file_write",
    "replace_text_in_file",
  ],
  "systemContext": {{
    "key":"value"
  }},
  "availableWorkflows": {{
    "流程名称": [
      "步骤1",
      "步骤2",
      "步骤3"
    ]
  }},
}}
""")

    args = parser.parse_args()

    # 读取预设运行配置文件
    preset_running_agent_config = {}
    if os.path.exists(args.preset_running_agent_config_path):
        with open(args.preset_running_agent_config_path, 'r', encoding='utf-8') as f:
            logger.info(f"读取预设运行配置文件: {args.preset_running_agent_config_path}")
            preset_running_agent_config = json.load(f)
            logger.info(f"预设运行配置内容: {preset_running_agent_config}")

    # 合并命令行参数和配置文件内容，命令行参数优先
    config = {
        'api_key': args.api_key,
        'model_name': args.model if args.model else preset_running_agent_config.get('llmConfig', {}).get('model', ''),
        'base_url': args.base_url,
        'tools_folders': args.tools_folders,
        'max_tokens': args.max_tokens if args.max_tokens else int(preset_running_agent_config.get('llmConfig', {}).get('maxTokens', 4096)),
        'temperature': args.temperature if args.temperature else float(preset_running_agent_config.get('llmConfig', {}).get('temperature', 0.2)),
        'use_deepthink': not args.no_deepthink if args.no_deepthink is not None else preset_running_agent_config.get('deepThinking', False),
        'use_multi_agent': not args.no_multi_agent if args.no_multi_agent is not None else preset_running_agent_config.get('multiAgent', False),
        'workspace': args.workspace,
        'mcp_setting_path': args.mcp_setting_path,
        'available_workflows': preset_running_agent_config.get('availableWorkflows', {}),
        'system_context': preset_running_agent_config.get('systemContext', {}),
        'available_tools': preset_running_agent_config.get('availableTools', []),
        'system_prefix': preset_running_agent_config.get('systemPrefix', ''),
        'max_loop_count': preset_running_agent_config.get('maxLoopCount', 10),
        'user_id': args.user_id,
        'memory_root': args.memory_root,
    }
    logger.info(f"config: {config}")
    return config


if __name__ == '__main__':
    config = parse_arguments()

    async def main_async():
        # 初始化tool manager
        tool_manager = ToolManager()
        await tool_manager._discover_mcp_tools(config['mcp_setting_path'])
        if config['available_tools']:
            tool_proxy = ToolProxy(tool_manager=tool_manager, available_tools=config['available_tools'])
        else:
            tool_proxy = tool_manager

        # 初始化 model
        client = AsyncOpenAI(
            api_key=config['api_key'],
            base_url=config['base_url']
        )
        client.model = config['model_name']

        # 初始化 SAgent
        sagent = SAgent(
            model=client,
            model_config={
                "model": config['model_name'],
                "max_tokens": config['max_tokens'],
                "temperature": config['temperature']
            },
            system_prefix=config['system_prefix'],
            workspace=config['workspace'],
            memory_root=config['memory_root'],
        )

        # 调用 chat 函数
        await chat(sagent, tool_proxy)

    import asyncio
    asyncio.run(main_async())
