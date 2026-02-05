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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sagents.context.messages.message import MessageChunk, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.fibre.agent import FibreAgent
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.utils.logger import logger
from sagents.utils.streaming_message_box import (
    StreamingMessageBox,
    display_items_in_columns,
    get_message_type_style
)
from rich.live import Live
from rich.panel import Panel
from rich.console import Group
from rich import box


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
            tool_names.sort()
            display_items_in_columns(tool_names, title="可用工具列表", color="cyan")
        else:
            console.print("[yellow]未检测到可用工具。[/yellow]")
    except Exception as e:
        logger.error(f"获取工具列表时出错: {traceback.format_exc()}")
        console.print(f"\n[red]获取工具列表时出错: {e}[/red]")


async def chat(agent: FibreAgent, tool_manager: Union[ToolManager, ToolProxy], skill_manager: Optional[Union[SkillManager, SkillProxy]] = None, config: Dict[str, Any] = None, context_budget_config: Optional[Dict[str, Any]] = None):
    console = Console()
    display_tools(console, tool_manager)

    if skill_manager:
        console.print(f"[cyan]已加载技能: {skill_manager.list_skills()}[/cyan]")

    console.print("[green]欢迎使用 FibreAgent CLI。输入 'exit' 或 'quit' 退出。[/green]")
    
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
                # active_states: agent_name -> {'id': str, 'type': str, 'content': str}
                active_states = {}
                
                def generate_live_view():
                    panels = []
                    # 按名称排序，保证显示顺序稳定
                    for name in sorted(active_states.keys()):
                        state = active_states[name]
                        color, label = get_message_type_style(state['type'])
                        
                        display_label = f"{label} | {name}"
                        
                        # 截取最后20行内容用于显示，避免刷屏
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
                    # 使用 Live 上下文管理器接管屏幕输出
                    # 关闭 auto_refresh，手动控制刷新以保证实时性
                    with Live(generate_live_view(), console=console, auto_refresh=False, vertical_overflow="visible") as live:
                        # Call FibreAgent run_stream
                        async for chunks in agent.run_stream(
                            input_messages=messages,
                            tool_manager=tool_manager,
                            skill_manager=skill_manager,
                            session_id=session_id,
                            user_id=config.get('user_id'),
                            system_context=config.get('system_context'),
                            context_budget_config=context_budget_config,
                            max_loop_count=config.get('max_loop_count', 10)
                        ):
                            for chunk in chunks:
                                if isinstance(chunk, MessageChunk):
                                    all_chunks.append(deepcopy(chunk))
                                    try:
                                        if chunk.show_content and chunk.type:
                                            agent_name = chunk.agent_name or "FibreAgent"
                                            
                                            # 初始化该 agent 的状态
                                            if agent_name not in active_states:
                                                active_states[agent_name] = {
                                                    'id': chunk.message_id,
                                                    'type': chunk.type or chunk.message_type or 'normal',
                                                    'content': ''
                                                }
                                            
                                            state = active_states[agent_name]
                                            
                                            # 如果 message_id 变化，说明上一条消息结束了
                                            if state['id'] != chunk.message_id:
                                                # 1. 将上一条消息作为静态 Panel 打印到控制台（Live 区域上方）
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
                                                
                                                # 2. 重置状态为新消息
                                                state['id'] = chunk.message_id
                                                state['type'] = chunk.type or chunk.message_type or 'normal'
                                                state['content'] = ""
                                            
                                            # 追加新内容
                                            content_to_add = str(chunk.show_content)
                                            state['content'] += content_to_add
                                            
                                            # 3. 更新 Live 视图并强制刷新
                                            live.update(generate_live_view(), refresh=True)
                                            
                                    except Exception:
                                        # 避免打印出错影响流程，改为记录日志或忽略
                                        # print(chunk) 
                                        pass

                        # 循环结束后，将所有剩余的活跃消息打印出来
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
                    
                    # 过滤掉非当前session的消息（例如子agent的消息），避免污染主session历史
                    main_session_chunks = [
                        c for c in all_chunks 
                        if c.session_id == session_id or c.session_id is None
                    ]
                    messages = MessageManager.merge_new_messages_to_old_messages(main_session_chunks, messages)
                    
                except asyncio.CancelledError:
                    # 即使被取消，也保存已经生成的消息
                    if all_chunks:
                        # 过滤掉非当前session的消息
                        main_session_chunks = [
                            c for c in all_chunks 
                            if c.session_id == session_id or c.session_id is None
                        ]
                        messages = MessageManager.merge_new_messages_to_old_messages(main_session_chunks, messages)
                    raise

            # 定义键盘监听任务
            async def monitor_keyboard():
                while True:
                    # 检查 stdin 是否有输入，超时 0.1s
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        try:
                            key = sys.stdin.read(1)
                            if key.lower() == 'q':
                                return True
                        except IOError:
                            pass
                    await asyncio.sleep(0.05)

            # 并发执行 Agent 和 键盘监听
            # 使用 tty.setcbreak 允许单字符读取
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
                # 恢复终端设置
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
        except KeyboardInterrupt:
            console.print("\n[yellow]检测到中断 (Ctrl+C)，正在停止...[/yellow]")
            # 确保任务被取消并等待其清理完成（包括保存session）
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
    parser = argparse.ArgumentParser(
        description='FibreAgent CLI Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--default_llm_api_key', required=True, help='默认LLM API Key')
    parser.add_argument('--default_llm_api_base_url', required=True, help='默认LLM API Base')
    parser.add_argument('--default_llm_model_name', required=True, help='默认LLM API Model')
    parser.add_argument('--default_llm_max_tokens', default=4096, type=int, help='默认LLM API Max Tokens')
    parser.add_argument('--default_llm_temperature', default=0.2, type=float, help='默认LLM API Temperature')
    parser.add_argument('--default_llm_max_model_len', default=54000, type=int, help='默认LLM 最大上下文')
    parser.add_argument('--default_llm_top_p', default=0.9, type=float, help='默认LLM Top P')
    parser.add_argument('--default_llm_presence_penalty', default=0.0, type=float, help='默认LLM Presence Penalty')

    parser.add_argument("--context_history_ratio", type=float, default=0.2, help='上下文预算管理器：历史消息的比例')
    parser.add_argument("--context_active_ratio", type=float, default=0.3, help='上下文预算管理器：活跃消息的比例')
    parser.add_argument("--context_max_new_message_ratio", type=float, default=0.5, help='上下文预算管理器：新消息的比例')
    parser.add_argument("--context_recent_turns", type=int, default=0, help='上下文预算管理器：限制最近的对话轮数')

    parser.add_argument('--user_id', type=str, default=None, help='用户ID')
    parser.add_argument('--memory_root', type=str, default=None, help='记忆根目录')
    parser.add_argument('--tools_folders', nargs='+', default=[], help='工具目录路径')
    parser.add_argument('--skills_path', type=str, default=None, help='技能目录路径')
    parser.add_argument('--workspace', type=str, default=os.path.join(os.getcwd(), 'agent_workspace'), help='工作目录')
    parser.add_argument('--mcp_setting_path', type=str, default=os.path.join(os.path.dirname(__file__), 'mcp_setting.json'), help="MCP 设置文件路径")
    parser.add_argument('--preset_running_agent_config_path', type=str, default=os.path.join(os.path.dirname(__file__), 'preset_running_agent_config.json'), help="预设运行配置文件路径")
    parser.add_argument('--memory_type', type=str, default='session', help='记忆类型 (session/user)')
    parser.add_argument('--no_terminal_log', action='store_true', help='停止终端打印log')

    args = parser.parse_args()

    preset_running_agent_config = {}
    if os.path.exists(args.preset_running_agent_config_path):
        with open(args.preset_running_agent_config_path, 'r', encoding='utf-8') as f:
            preset_running_agent_config = json.load(f)

    config = {
        'api_key': args.default_llm_api_key,
        'model_name': args.default_llm_model_name if args.default_llm_model_name else preset_running_agent_config.get('llmConfig', {}).get('model', ''),
        'base_url': args.default_llm_api_base_url,
        'tools_folders': args.tools_folders,
        'skills_path': args.skills_path,
        'max_tokens': args.default_llm_max_tokens,
        'temperature': args.default_llm_temperature,
        'max_model_len': args.default_llm_max_model_len,
        'top_p': args.default_llm_top_p,
        'presence_penalty': args.default_llm_presence_penalty,
        'workspace': args.workspace,
        'mcp_setting_path': args.mcp_setting_path,
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
        'memory_type': args.memory_type,
        'no_terminal_log': args.no_terminal_log,
    }
    return config


if __name__ == '__main__':
    config = parse_arguments()

    async def main_async():
        # 如果配置了禁止终端日志，移除console handler
        if config.get('no_terminal_log'):
            # 移除 sage logger 的 handler
            for handler in logger.logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                    logger.logger.removeHandler(handler)
            
            # 移除 root logger 的 handler，防止其他库（如 httpx, rich 等）输出日志
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                # 移除所有非文件handler
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
            
            # 防止其他未命名logger传播到root (虽然这可能比较激进，但对于CLI工具是合理的)
            # logging.getLogger().setLevel(logging.WARNING) # 这会影响所有logger，可能太强了

        tool_manager = ToolManager()
        await tool_manager._discover_mcp_tools(config['mcp_setting_path'])
        if config['available_tools']:
            tool_proxy = ToolProxy(tool_manager=tool_manager, available_tools=config['available_tools'])
        else:
            tool_proxy = tool_manager

        skill_manager = None
        if config['skills_path']:
            skill_manager = SkillManager(skill_dirs=[config['skills_path']])

        client = AsyncOpenAI(
            api_key=config['api_key'],
            base_url=config['base_url']
        )
        client.model = config['model_name']

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

        if config['memory_root']:
            os.environ["MEMORY_ROOT_PATH"] = config['memory_root']

        agent = FibreAgent(
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

        await chat(agent, tool_proxy, skill_manager, config, context_budget_config)

    asyncio.run(main_async())
