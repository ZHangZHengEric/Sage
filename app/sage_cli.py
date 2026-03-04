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

from openai import AsyncOpenAI
from rich.console import Console
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.widgets import Frame, TextArea, Label
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import to_filter

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
    display_items_in_columns
)


def display_tools(console, tool_manager: Union[ToolManager, ToolProxy]):
    """显示可用的工具列表（简化为一行）"""
    tools = tool_manager.get_openai_tools()
    tool_names = [tool['function']['name'] for tool in tools]
    console.print(f"\n[dim]可用工具: {', '.join(tool_names)}[/dim]")


def select_skill_interactive(console, skill_manager, initial_input: str = "") -> Optional[str]:
    """
    交互式选择 skill
    当用户输入 / 时调用，显示 skills 列表并允许选择
    
    Args:
        skill_manager: SkillManager 实例
        initial_input: 用户已输入的内容（以 / 开头）
        
    Returns:
        选中的 skill 名称，或 None（用户取消）
    """
    from prompt_toolkit import Application
    from prompt_toolkit.widgets import TextArea, Label, Button
    from prompt_toolkit.layout import Layout, HSplit, VSplit, Frame
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.filter import to_filter
    
    skills = skill_manager.list_skills()
    if not skills:
        console.print("[yellow]没有已加载的技能[/yellow]")
        return None
    
    filtered_skills = skills.copy()
    selected_index = 0
    
    # 创建 UI 组件
    skill_list_label = Label("")
    input_area = TextArea(
        text=initial_input[1:] if initial_input.startswith('/') else initial_input,
        multiline=False,
        accept_handler=None
    )
    
    def update_display():
        """更新显示"""
        nonlocal filtered_skills, selected_index
        
        query = input_area.text.lower().strip()
        if query:
            filtered_skills = [s for s in skills if query in s.lower()]
        else:
            filtered_skills = skills.copy()
        
        selected_index = 0
        
        # 更新列表显示
        lines = []
        for i, skill in enumerate(filtered_skills):
            prefix = "▶ " if i == selected_index else "  "
            lines.append(f"{prefix}{skill}")
        
        skill_list_label.text = "\n".join(lines)
    
    # 创建 key bindings
    kb = KeyBindings()
    
    @kb.add('c-c', filter=to_filter(True))
    def cancel(event):
        event.app.exit(result=None)
    
    @kb.add('c-q', filter=to_filter(True))
    def cancel2(event):
        event.app.exit(result=None)
    
    @kb.add('escape', filter=to_filter(True))
    def cancel3(event):
        event.app.exit(result=None)
    
    @kb.add('up', filter=to_filter(True))
    def move_up(event):
        nonlocal selected_index
        if filtered_skills:
            selected_index = (selected_index - 1) % len(filtered_skills)
            update_display()
    
    @kb.add('down', filter=to_filter(True))
    def move_down(event):
        nonlocal selected_index
        if filtered_skills:
            selected_index = (selected_index + 1) % len(filtered_skills)
            update_display()
    
    @kb.add('enter', filter=to_filter(True))
    def select(event):
        if filtered_skills and 0 <= selected_index < len(filtered_skills):
            event.app.exit(result=filtered_skills[selected_index])
    
    # 布局
    container = VSplit([
        Label("[bold]技能列表 (↑↓ 选择, Enter 确认, Esc 取消):[/bold]\n"),
        skill_list_label,
        Label("\n[bold]搜索:[/bold]"),
        input_area,
    ])
    
    # 初始化显示
    update_display()
    
    # 运行应用
    app = Application(
        layout=Layout(container),
        key_bindings=kb,
        mouse_support=True,
    )
    
    try:
        result = app.run()
        return result
    except Exception:
        return None


async def chat_simple(agent: SAgent, tool_manager: Union[ToolManager, ToolProxy], skill_manager: Optional[Union[SkillManager, SkillProxy]], config: Dict[str, Any], context_budget_config: Optional[Dict[str, Any]] = None):
    """
    原 sage_cli.py 的对话逻辑，适用于 simple 和 multi 模式
    """
    console = Console()
    display_tools(console, tool_manager)

    if skill_manager:
        console.print(f"[cyan]已加载技能: {skill_manager.list_skills()}[/cyan]")

    console.print(f"[green]欢迎使用 SAgent CLI ({config.get('agent_mode', 'simple')} 模式)。输入 'exit' 或 'quit' 退出。[/green]")
    
    # 使用配置的 session_id 或生成新的
    if config.get('session_id'):
        session_id = config['session_id']
    else:
        session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_'+str(uuid.uuid4())[:4]
    console.print(f"[dim]当前session id: {session_id}[/dim]")

    messages = []
    while True:
        try:
            # 使用 input() 替代 console.input()，更好地支持中文
            user_input = input("\033[1;34m你: \033[0m")
            
            # 处理 / 开头的情况 - 显示技能列表
            if user_input.startswith('/') and skill_manager:
                console.print("\n[cyan]=== 技能选择模式 ===[/cyan]")
                try:
                    selected_skill = select_skill_interactive(console, skill_manager, user_input)
                except Exception as e:
                    console.print(f"[red]技能选择出错: {e}[/red]")
                    console.print(f"[yellow]可用技能: {skill_manager.list_skills()}[/yellow]")
                    continue
                
                if selected_skill:
                    console.print(f"[green]已选择技能: {selected_skill}[/green]")
                    user_input = f"/使用技能 {selected_skill}"
                else:
                    console.print("[yellow]取消选择[/yellow]")
                    continue
            
            if user_input.lower() in ['exit', 'quit']:
                console.print("[green]再见！[/green]")
                break

            console.print("[magenta]SAgent:[/magenta]")
            last_message_id = None
            messages.append(MessageChunk(role='user', content=user_input, type=MessageType.NORMAL.value))
            all_chunks = []
            current_message_box = None
            first_args = True
            # 为每个 tool_call 维护状态
            tool_call_parsers: Dict[str, bool] = {}

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
                                if current_message_box is not None and (chunk.content or chunk.tool_calls):
                                    current_message_box.finish()

                                # 创建新的消息框
                                if (chunk.content or chunk.tool_calls) and chunk.type:
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
                        
                        # 处理 tool_calls（流式增量）
                        if chunk.tool_calls and current_message_box:
                            for tool_call in chunk.tool_calls:
                                # 获取 tool_call_id, tool_name 和 tool_args
                                if hasattr(tool_call, 'id'):
                                    tc_id = tool_call.id
                                else:
                                    tc_id = tool_call.get('id')

                                if hasattr(tool_call, 'function'):
                                    tool_name = tool_call.function.name if hasattr(tool_call.function, 'name') else None
                                    tool_args = tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else None
                                else:
                                    tool_name = tool_call.get('function', {}).get('name')
                                    tool_args = tool_call.get('function', {}).get('arguments')

                                # 新的 tool_call，显示工具名和参数
                                if tc_id not in tool_call_parsers:
                                    tool_call_parsers[tc_id] = True
                                    if tool_name:
                                        prefix = f"\nTool:  {tool_name}:\n    {tool_args}" if tool_args else f"\n🛠️  {tool_name}"
                                        for char in prefix:
                                            current_message_box.add_content(char)
                                    if tool_args:
                                        first_args = False
                                    else:
                                        first_args = True
                                elif tool_args:
                                    # 增量显示参数
                                    if first_args:
                                        for char in "\n    " + tool_args:
                                            current_message_box.add_content(char)
                                        first_args = False
                                    else:
                                        for char in tool_args:
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
    # 使用配置的 session_id 或生成新的
    if config.get('session_id'):
        session_id = config['session_id']
    else:
        session_id = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()) + '_' + str(uuid.uuid4())[:4]
    messages = []
    agent_task = None
    active_states: Dict[str, Dict[str, Any]] = {session_id: {"order": [], "messages": {}}}
    panels: Dict[str, TextArea] = {}
    frames: Dict[str, Frame] = {}
    panel_order = [session_id]
    input_area = TextArea(height=5, prompt="> ", multiline=True, focus_on_click=True)
    input_area.buffer.complete_while_typing = to_filter(False)
    layout = Layout(HSplit([Label(text=" ")]))
    kb = KeyBindings()
    app = None
    execution_status = "就绪"

    def build_tools_text():
        if hasattr(tool_manager, 'list_tools_simplified'):
            available_tools = tool_manager.list_tools_simplified()
        elif hasattr(tool_manager, 'tool_manager') and hasattr(tool_manager.tool_manager, 'list_tools_simplified'):
            available_tools = tool_manager.tool_manager.list_tools_simplified()
        else:
            available_tools = []
        if not available_tools:
            return "未检测到可用工具。"
        tool_names = [tool.get('name', '未知工具') for tool in available_tools]
        tool_names.sort()
        lines = [f"{idx + 1}. {name}" for idx, name in enumerate(tool_names)]
        return "📋 可用工具列表(共{}个)：\n{}".format(len(tool_names), "\n".join(lines))

    def append_log(text):
        msg_id = str(uuid.uuid4())
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        active_states.setdefault(session_id, {"order": [], "messages": {}})
        active_states[session_id]["messages"][msg_id] = {
            "agent_name": "System",
            "content": text,
            "timestamp": timestamp,
            "type": "system"
        }
        active_states[session_id]["order"].append(msg_id)

    def ensure_panel(sid: str):
        if sid in panels:
            return
        panel = TextArea(text="", read_only=True, scrollbar=True, focusable=True, focus_on_click=True)
        panels[sid] = panel
        title = f"主会话 {sid}" if sid == session_id else f"子会话 {sid}"
        frames[sid] = Frame(panel, title=title)
        if sid not in panel_order:
            panel_order.append(sid)
        rebuild_layout()

    def rebuild_layout():
        panel_frames = [frames[sid] for sid in panel_order if sid in frames]
        if not panel_frames:
            panel_frames = [Frame(TextArea(text="暂无内容", read_only=True), title="Session")]
        if len(panel_frames) == 1:
            panel_row = panel_frames[0]
        else:
            panel_row = VSplit(panel_frames, padding=1)
        layout.container = HSplit([panel_row, input_area])

    def render_session_text(sid: str):
        session_states = active_states.get(sid, {})
        if not session_states:
            return ""
        session_messages = session_states.get("messages", {})
        session_order = session_states.get("order", [])
        if not session_messages:
            return ""
        message_lines = []
        for message_id in session_order[-1000:]:
            state = session_messages.get(message_id)
            if not state:
                continue
            agent_name = state.get('agent_name') or 'FibreAgent'
            timestamp = state.get('timestamp') or ""
            content = state.get('content') or ""
            
            if not content or not content.strip():
                continue

            prefix = f"[{timestamp}] {agent_name}" if timestamp else f"{agent_name}"
            content_lines = content.splitlines()
            
            if content_lines:
                # 消息头单独一行
                message_lines.append(f"{prefix}:")
                # 消息内容另起一行
                for line in content_lines:
                    message_lines.append(line)
            message_lines.append("")
        if message_lines and message_lines[-1] == "":
            message_lines.pop()
        return "\n".join(message_lines)

    def update_panel_text(sid: str):
        panel = panels.get(sid)
        if not panel:
            return
        session_text = render_session_text(sid)
        panel.text = session_text
        panel.buffer.cursor_position = len(panel.text)

    def refresh_all():
        for sid in list(panels.keys()):
            update_panel_text(sid)
            if sid in frames:
                base_title = f"主会话 {sid}" if sid == session_id else f"子会话 {sid}"
                frames[sid].title = f"{base_title} ({execution_status})"
        if app:
            app.invalidate()

    append_log(build_tools_text())
    if skill_manager:
        append_log(f"已加载技能: {skill_manager.list_skills()}")
    append_log("欢迎使用 SAgent CLI (Fibre 模式)。输入 'exit' 或 'quit' 退出。")
    append_log("输入：Enter 发送，Meta+Enter (Option+Enter) 换行")
    append_log(f"当前session id: {session_id}")
    ensure_panel(session_id)
    refresh_all()

    @kb.add('c-c')
    def _(event):
        event.app.exit()
    
    @kb.add('enter')
    def _(event):
        event.app.current_buffer.validate_and_handle()

    @kb.add('escape', 'enter')
    def _(event):
        event.app.current_buffer.insert_text('\n')

    async def run_agent_execution(user_input: str):
        nonlocal messages, agent_task, execution_status
        execution_status = "执行中"
        # 记录用户消息
        user_msg_id = str(uuid.uuid4())
        user_timestamp = time.strftime("%H:%M:%S", time.localtime())
        active_states.setdefault(session_id, {"order": [], "messages": {}})
        active_states[session_id]["messages"][user_msg_id] = {
            "agent_name": "你",
            "content": user_input,
            "timestamp": user_timestamp,
            "type": "user"
        }
        active_states[session_id]["order"].append(user_msg_id)
        
        refresh_all()
        messages.append(MessageChunk(role='user', content=user_input, type=MessageType.NORMAL.value))
        all_chunks = []
        try:
            async for chunks in agent.run_stream(
                input_messages=messages,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                session_id=session_id,
                user_id=config.get('user_id'),
                deep_thinking=config.get('use_deepthink'),
                agent_mode='fibre',
                available_workflows=config.get('available_workflows'),
                system_context=config.get('system_context'),
                context_budget_config=context_budget_config,
                max_loop_count=config.get('max_loop_count', 100)
            ):
                for chunk in chunks:
                    if isinstance(chunk, MessageChunk):
                        all_chunks.append(deepcopy(chunk))
                        # 处理 content 或 tool_calls
                        if chunk.content is not None or chunk.type or chunk.tool_calls:
                            agent_name = chunk.agent_name or "FibreAgent"
                            chunk_session_id = chunk.session_id or session_id
                            session_states = active_states.setdefault(chunk_session_id, {"order": [], "messages": {}})
                            session_messages = session_states["messages"]
                            message_id = chunk.message_id
                            state = session_messages.get(message_id)
                            if not state:
                                state = {
                                    'type': chunk.type or chunk.message_type or 'normal',
                                    'content': '',
                                    'agent_name': agent_name,
                                    'timestamp': time.strftime("%H:%M:%S", time.localtime())
                                }
                                session_messages[message_id] = state
                                session_states["order"].append(message_id)
                            state['type'] = chunk.type or chunk.message_type or 'normal'
                            if chunk.content is not None:
                                content_to_add = str(chunk.content)
                                # 始终追加内容，避免相同 message_id 的内容被覆盖
                                state['content'] += content_to_add
                            # 处理 tool_calls 显示
                            if chunk.tool_calls:
                                for tool_call in chunk.tool_calls:
                                    if hasattr(tool_call, 'function'):
                                        tool_name = tool_call.function.name if hasattr(tool_call.function, 'name') else None
                                        tool_args = tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else None
                                    else:
                                        tool_name = tool_call.get('function', {}).get('name')
                                        tool_args = tool_call.get('function', {}).get('arguments')
                                    if tool_name:
                                        state['content'] += f"\n[Tool Call: {tool_name}]"
                                        if tool_args:
                                            state['content'] += f"\nArgs: {tool_args}"
                            ensure_panel(chunk_session_id)
                            refresh_all()
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
        except Exception as e:
            append_log(f"执行出错: {e}")
            refresh_all()
            traceback.print_exc()
        finally:
            agent_task = None
            execution_status = "已完成"
            refresh_all()

    def accept(buff):
        nonlocal agent_task
        cmd = buff.text.strip()
        if not cmd:
            return False
        if cmd.lower() in ['exit', 'quit']:
            if app:
                app.exit()
            return False
        if agent_task and not agent_task.done():
            append_log("当前有任务执行中，请稍候。")
            refresh_all()
            buff.text = ""
            return False
        agent_task = asyncio.create_task(run_agent_execution(cmd))
        buff.text = ""
        return False

    input_area.accept_handler = accept
    input_area.buffer.completer = None

    @kb.add('c-s')
    def _(event):
        event.app.current_buffer.validate_and_handle()

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True
    )

    await app.run_async()


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
    parser.add_argument('--session_id', type=str, default=None, help='指定会话 ID（可选）')
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
        'session_id': args.session_id,
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
    # 设置终端编码，确保中文输入正常
    import sys
    import os
    
    # 设置 Python 的标准流编码
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stdin.encoding != 'utf-8':
        sys.stdin.reconfigure(encoding='utf-8')
    
    # 设置 readline 相关环境变量
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['LC_ALL'] = 'zh_CN.UTF-8'
    
    # 配置 readline 以正确处理 UTF-8
    try:
        import readline
        # 设置破折号/引号字符不做转义
        readline.parse_and_bind('set enable-bracketed-paste off')
        readline.parse_and_bind('set editing-mode emacs')
    except:
        pass
    
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
