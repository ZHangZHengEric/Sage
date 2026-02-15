import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid
from copy import deepcopy
from typing import Any, Dict, Optional, Union
import select
import tty
import termios

from openai import AsyncOpenAI
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.console import Group
from rich import box

sys.path.append((os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
print(f'添加路径：{(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))}')

from sagents.context.messages.message import MessageChunk, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.sagents import SAgent
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.utils.logger import logger
from sagents.utils.streaming_message_box import (
    StreamingMessageBox,
    display_items_in_columns,
    get_message_type_style
)



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


async def chat_simple(agent: SAgent, tool_manager: Union[ToolManager, ToolProxy], skill_manager: Optional[Union[SkillManager, SkillProxy]], config: Dict[str, Any], context_budget_config: Optional[Dict[str, Any]] = None):
    """
    原 sage_cli.py 的对话逻辑，适用于 simple 和 multi 模式
    """
    console = Console()
    display_tools(console, tool_manager)

    if skill_manager:
        console.print(f"[cyan]已加载技能: {skill_manager.list_skills()}[/cyan]")

    console.print(f"[green]欢迎使用 SAgent CLI ({config.get('agent_mode', 'simple')} 模式)。输入 'exit' 或 'quit' 退出。[/green]")
    
    session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_'+str(uuid.uuid4())[:4]
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

            async for chunks in agent.run_stream(
                input_messages=messages,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                session_id=session_id,
                user_id=config['user_id'],
                deep_thinking=config['use_deepthink'],
                agent_mode=config.get('agent_mode'), # 传入 agent_mode
                available_workflows=config['available_workflows'],
                system_context=config['system_context'],
                context_budget_config=context_budget_config
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
                                if chunk.content and chunk.type:
                                    message_type = chunk.type or chunk.message_type or 'normal'
                                    current_message_box = StreamingMessageBox(console, message_type)

                                last_message_id = chunk.message_id
                        except Exception:
                            print(chunk)

                        if chunk.content and current_message_box:
                            # 确保 content 是字符串
                            content_to_print = str(chunk.content)
                            for char in content_to_print:
                                current_message_box.add_content(char)

            # 完成最后一个消息框
            if current_message_box is not None:
                current_message_box.finish()

            console.print("")
            messages = MessageManager.merge_new_messages_to_old_messages(all_chunks, messages)
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


async def chat_fibre(agent: SAgent, tool_manager: Union[ToolManager, ToolProxy], skill_manager: Optional[Union[SkillManager, SkillProxy]], config: Dict[str, Any], context_budget_config: Optional[Dict[str, Any]] = None):
    """
    原 fibre_cli.py 的对话逻辑，适用于 fibre 模式，支持多 Agent 面板显示和键盘中断
    """
    console = Console()
    display_tools(console, tool_manager)

    if skill_manager:
        console.print(f"[cyan]已加载技能: {skill_manager.list_skills()}[/cyan]")

    console.print(f"[green]欢迎使用 SAgent CLI (Fibre 模式)。输入 'exit' 或 'quit' 退出。[/green]")
    
    session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_'+str(uuid.uuid4())[:4]
    console.print(f"[dim]当前session id: {session_id}[/dim]")

    messages = []
    agent_task = None
    monitor_task = None
    
    while True:
        try:
            user_input = console.input("[bold blue]你: [/bold blue]")
            if user_input.lower() in ['exit', 'quit']:
                console.print("[green]再见！[/green]")
                break

            console.print("[magenta]FibreAgent:[/magenta]")
            
            # 添加用户输入到消息列表
            messages.append(MessageChunk(role='user', content=user_input, type=MessageType.NORMAL.value))
            
            # 定义执行任务
            async def run_agent_execution():
                nonlocal messages
                all_chunks = []
                
                # 用于 Live Display 的状态管理
                active_states = {}
                
                def generate_live_view():
                    panels = []
                    for name in sorted(active_states.keys()):
                        state = active_states[name]
                        color, label = get_message_type_style(state['type'])
                        
                        display_label = f"{label} | {name}"
                        
                        content = state['content']
                        lines = content.split('\n')
                        if len(lines) > 20:
                            content = "...\n" + "\n".join(lines[-20:])
                        
                        panels.append(Panel(
                            content,
                            title=display_label,
                            border_style=color,
                            box=box.ROUNDED,
                            padding=(0, 1)
                        ))
                    return Group(*panels)

                try:
                    with Live(generate_live_view(), console=console, auto_refresh=False, vertical_overflow="visible") as live:
                        async for chunks in agent.run_stream(
                            input_messages=messages,
                            tool_manager=tool_manager,
                            skill_manager=skill_manager,
                            session_id=session_id,
                            user_id=config.get('user_id'),
                            deep_thinking=config.get('use_deepthink'), # Fibre 模式下也传入 deep_thinking
                            agent_mode='fibre', # 强制 Fibre 模式
                            available_workflows=config.get('available_workflows'),
                            system_context=config.get('system_context'),
                            context_budget_config=context_budget_config,
                            max_loop_count=config.get('max_loop_count', 10)
                        ):
                            for chunk in chunks:
                                if isinstance(chunk, MessageChunk):
                                    all_chunks.append(deepcopy(chunk))
                                    try:
                                        if chunk.content and chunk.type:
                                            agent_name = chunk.agent_name or "FibreAgent"
                                            
                                            if agent_name not in active_states:
                                                active_states[agent_name] = {
                                                    'id': chunk.message_id,
                                                    'type': chunk.type or chunk.message_type or 'normal',
                                                    'content': ''
                                                }
                                            
                                            state = active_states[agent_name]
                                            
                                            if state['id'] != chunk.message_id:
                                                if state['content']:
                                                    color, label = get_message_type_style(state['type'])
                                                    display_label = f"{label} | {agent_name}"
                                                    static_panel = Panel(
                                                        state['content'],
                                                        title=display_label,
                                                        border_style=color,
                                                        box=box.ROUNDED,
                                                        padding=(0, 1)
                                                    )
                                                    live.console.print(static_panel)
                                                
                                                state['id'] = chunk.message_id
                                                state['type'] = chunk.type or chunk.message_type or 'normal'
                                                state['content'] = ""
                                            
                                            content_to_add = str(chunk.content)
                                            state['content'] += content_to_add
                                            live.update(generate_live_view(), refresh=True)
                                            
                                    except Exception:
                                        pass

                        for name in sorted(active_states.keys()):
                            state = active_states[name]
                            if state['content']:
                                color, label = get_message_type_style(state['type'])
                                display_label = f"{label} | {name}"
                                final_panel = Panel(
                                    state['content'],
                                    title=display_label,
                                    border_style=color,
                                    box=box.ROUNDED,
                                    padding=(0, 1)
                                )
                                live.console.print(final_panel)
                    
                    console.print("")
                    
                    main_session_chunks = [
                        c for c in all_chunks 
                        if c.session_id == session_id or c.session_id is None
                    ]
                    messages = MessageManager.merge_new_messages_to_old_messages(main_session_chunks, messages)
                    
                except asyncio.CancelledError:
                    if all_chunks:
                        main_session_chunks = [
                            c for c in all_chunks 
                            if c.session_id == session_id or c.session_id is None
                        ]
                        messages = MessageManager.merge_new_messages_to_old_messages(main_session_chunks, messages)
                    raise

            # 定义键盘监听任务
            async def monitor_keyboard():
                while True:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        try:
                            key = sys.stdin.read(1)
                            if key.lower() == 'q':
                                return True
                        except IOError:
                            pass
                    await asyncio.sleep(0.05)

            # 并发执行 Agent 和 键盘监听
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                
                agent_task = asyncio.create_task(run_agent_execution())
                monitor_task = asyncio.create_task(monitor_keyboard())
                
                done, pending = await asyncio.wait(
                    [agent_task, monitor_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                if monitor_task in done:
                    # 用户按了 q
                    console.print("\n[yellow]检测到中断请求 (Q)，正在停止...[/yellow]")
                    agent_task.cancel()
                    try:
                        await agent_task
                    except asyncio.CancelledError:
                        pass
                else:
                    # Agent 执行完成
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass
                        
            except Exception as e:
                console.print(f"[red]执行出错: {e}[/red]")
                traceback.print_exc()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
        except KeyboardInterrupt:
            console.print("\n[yellow]检测到中断 (Ctrl+C)，正在停止...[/yellow]")
            if agent_task and not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

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
  python sage_cli.py --default_llm_api_key YOUR_API_KEY --default_llm_model_name gpt-4 --agent_mode fibre
        """
    )

    # 与 sage_server.py 保持一致的参数
    parser.add_argument('--default_llm_api_key', required=True, help='默认LLM API Key')
    parser.add_argument('--default_llm_api_base_url', required=True, help='默认LLM API Base')
    parser.add_argument('--default_llm_model_name', required=True, help='默认LLM API Model')
    parser.add_argument('--default_llm_max_tokens', default=4096, type=int, help='默认LLM API Max Tokens')
    parser.add_argument('--default_llm_temperature', default=0.2, type=float, help='默认LLM API Temperature')
    parser.add_argument('--default_llm_max_model_len', default=54000, type=int, help='默认LLM 最大上下文')
    parser.add_argument('--default_llm_top_p', default=0.9, type=float, help='默认LLM Top P')
    parser.add_argument('--default_llm_presence_penalty', default=0.0, type=float, help='默认LLM Presence Penalty')

    parser.add_argument("--context_history_ratio", type=float, default=0.2,
                        help='上下文预算管理器：历史消息的比例（0-1之间）')
    parser.add_argument("--context_active_ratio", type=float, default=0.3,
                        help='上下文预算管理器：活跃消息的比例（0-1之间）')
    parser.add_argument("--context_max_new_message_ratio", type=float, default=0.5,
                        help='上下文预算管理器：新消息的比例（0-1之间）')
    parser.add_argument("--context_recent_turns", type=int, default=0,
                        help='上下文预算管理器：限制最近的对话轮数，0表示不限制')

    parser.add_argument('--user_id', type=str, default=None, help='用户ID')
    parser.add_argument('--memory_root', type=str, default=None, help='记忆根目录')
    parser.add_argument('--tools_folders', nargs='+', default=[], help='工具目录路径（多个路径用空格分隔）')
    parser.add_argument('--skills_path', type=str, default=None, help='技能目录路径')
    parser.add_argument('--deepthink', action='store_true', default=None, help='开启深度思考')
    parser.add_argument('--no-deepthink', action='store_true', default=None, help='禁用深度思考')
    parser.add_argument('--agent_mode', type=str, default=None, choices=['fibre', 'simple', 'multi'], help='智能体模式: fibre, simple, multi')
    
    parser.add_argument('--no_terminal_log', action='store_true', default=True, help='停止终端打印log (默认开启)')
    parser.add_argument('--show_terminal_log', action='store_false', dest='no_terminal_log', help='开启终端打印log')
    parser.add_argument('--workspace', type=str, default=os.path.join(os.getcwd(), 'agent_workspace'), help='工作目录')
    parser.add_argument('--mcp_setting_path', type=str, default=os.path.join(os.path.dirname(__file__), 'mcp_setting.json'),
                        help="""MCP 设置文件路径，文件内容为json格式""")
    parser.add_argument('--preset_running_agent_config_path', type=str, default=os.path.join(os.path.dirname(__file__), 'preset_running_agent_config.json'),
                        help="""预设运行配置文件路径""")
    parser.add_argument('--memory_type', type=str, default='session', help='记忆类型 (session/user)')

    args = parser.parse_args()

    # 读取预设运行配置文件
    preset_running_agent_config = {}
    if os.path.exists(args.preset_running_agent_config_path):
        with open(args.preset_running_agent_config_path, 'r', encoding='utf-8') as f:
            logger.info(f"读取预设运行配置文件: {args.preset_running_agent_config_path}")
            preset_running_agent_config = json.load(f)
            logger.info(f"预设运行配置内容: {preset_running_agent_config}")

    # 确定 agent_mode
    agent_mode = args.agent_mode
    if agent_mode is None:
        if preset_running_agent_config.get('agentMode'):
            agent_mode = preset_running_agent_config.get('agentMode')
        elif preset_running_agent_config.get('multiAgent') is True:
            agent_mode = 'multi'
        else:
            agent_mode = 'simple' # 默认为 simple

    # 确定 use_deepthink
    use_deepthink = preset_running_agent_config.get('deepThinking', False)
    if args.deepthink is not None:
        use_deepthink = args.deepthink
    elif args.no_deepthink is not None:
        use_deepthink = not args.no_deepthink
            
    # 合并命令行参数和配置文件内容，命令行参数优先
    config = {
        'api_key': args.default_llm_api_key,
        'model_name': args.default_llm_model_name if args.default_llm_model_name else preset_running_agent_config.get('llmConfig', {}).get('model', ''),
        'base_url': args.default_llm_api_base_url,
        'tools_folders': args.tools_folders,
        'skills_path': args.skills_path,
        'max_tokens': args.default_llm_max_tokens if args.default_llm_max_tokens else int(preset_running_agent_config.get('llmConfig', {}).get('maxTokens', 4096)),
        'temperature': args.default_llm_temperature if args.default_llm_temperature else float(preset_running_agent_config.get('llmConfig', {}).get('temperature', 0.2)),
        'max_model_len': args.default_llm_max_model_len,
        'top_p': args.default_llm_top_p,
        'presence_penalty': args.default_llm_presence_penalty,
        'use_deepthink': use_deepthink,
        'agent_mode': agent_mode,
        'workspace': args.workspace,
        'mcp_setting_path': args.mcp_setting_path,
        'available_workflows': preset_running_agent_config.get('availableWorkflows', {}),
        'system_context': preset_running_agent_config.get('systemContext', {}),
        'available_tools': preset_running_agent_config.get('availableTools', []),
        'system_prefix': preset_running_agent_config.get('systemPrefix', ''),
        'max_loop_count': preset_running_agent_config.get('maxLoopCount', 10),
        'user_id': args.user_id,
        'memory_root': args.memory_root,
        'context_history_ratio': args.context_history_ratio,
        'context_active_ratio': args.context_active_ratio,
        'context_max_new_message_ratio': args.context_max_new_message_ratio,
        'context_recent_turns': args.context_recent_turns,
        'no_terminal_log': args.no_terminal_log,
        'memory_type': args.memory_type if args.memory_type else preset_running_agent_config.get('memoryType', 'session'),
    }
    logger.info(f"config: {config}")
    return config


if __name__ == '__main__':
    config = parse_arguments()

    async def main_async():
        if config.get('no_terminal_log'):
            # 移除 sage logger 的 handler
            for handler in logger.logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                    logger.logger.removeHandler(handler)
            
            # 移除 root logger 的 handler，防止其他库（如 httpx, rich 等）输出日志
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                if not isinstance(handler, logging.FileHandler):
                    root_logger.removeHandler(handler)
            
            # 强制设置 noisy loggers 为 WARNING 级别
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)
            logging.getLogger("openai").setLevel(logging.WARNING)
            
            # 针对 sagents 内部模块设置 ERROR 级别，屏蔽 INFO 级别的工具调用和编排日志
            logging.getLogger("sagents").setLevel(logging.ERROR)
            logging.getLogger("sagents.fibre.tools").setLevel(logging.ERROR)
            logging.getLogger("sagents.fibre.orchestrator").setLevel(logging.ERROR)

        # 初始化tool manager
        tool_manager = ToolManager()
        await tool_manager._discover_mcp_tools(config['mcp_setting_path'])
        if config['available_tools']:
            tool_proxy = ToolProxy(tool_manager=tool_manager, available_tools=config['available_tools'])
        else:
            tool_proxy = tool_manager

        # 初始化 skill manager
        skill_manager = None
        if config['skills_path']:
            skill_manager = SkillManager(skill_dirs=[config['skills_path']])

        # 初始化 model
        client = AsyncOpenAI(
            api_key=config['api_key'],
            base_url=config['base_url']
        )
        client.model = config['model_name']

        # 构建context_budget_config字典
        context_budget_config = {
            'max_model_len': config['max_model_len']
        }
        if config['context_history_ratio'] is not None:
            context_budget_config['history_ratio'] = config['context_history_ratio']
        if config['context_active_ratio'] is not None:
            context_budget_config['active_ratio'] = config['context_active_ratio']
        if config['context_max_new_message_ratio'] is not None:
            context_budget_config['max_new_message_ratio'] = config['context_max_new_message_ratio']
        if config['context_recent_turns'] is not None:
            context_budget_config['recent_turns'] = config['context_recent_turns']

        # 初始化 SAgent
        # 如果指定了 memory_root，则设置环境变量
        if config['memory_root']:
            os.environ["MEMORY_ROOT_PATH"] = config['memory_root']

        sagent = SAgent(
            model=client,
            model_config={
                "model": config['model_name'],
                "max_tokens": config['max_tokens'],
                "temperature": config['temperature'],
                "max_model_len": config['max_model_len'],
                "top_p": config['top_p'],
                "presence_penalty": config['presence_penalty']
            },
            system_prefix=config['system_prefix'],
            workspace=config['workspace'],
            memory_type=config['memory_type'],
        )

        # 根据模式选择不同的 chat 函数
        if config['agent_mode'] == 'fibre':
            await chat_fibre(sagent, tool_proxy, skill_manager, config, context_budget_config)
        else:
            await chat_simple(sagent, tool_proxy, skill_manager, config, context_budget_config)

    asyncio.run(main_async())
