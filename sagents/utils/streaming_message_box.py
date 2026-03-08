import shutil
from typing import Tuple, List
import os
from rich.console import Console
from rich.text import Text

console = Console()


def get_message_type_style(message_type: str) -> Tuple[str, str]:
    """获取消息类型的颜色和标签
    
    Args:
        message_type: 消息类型
        
    Returns:
        tuple: (颜色, 标签)
    """
    type_styles = {
        'normal': ('blue', '💬 普通消息'),
        'task_analysis': ('cyan', '🔍 任务分析'),
        'task_decomposition': ('yellow', '📋 任务拆解'),
        'planning': ('magenta', '📝 规划'),
        'execution': ('green', '🚀 执行'),
        'observation': ('bright_blue', '👀 观察'),
        'final_answer': ('bright_green', '✅ 最终答案'),
        'thinking': ('white', '🤔 思考'),
        'tool_call': ('bright_yellow', '🔧 工具调用'),
        'tool_response': ('bright_magenta', '🏁 工具响应'),
        'tool_call_result': ('bright_magenta', '🏁 工具结果'),
        'error': ('red', '❌ 错误'),
        'system': ('bright_black', '🏁 系统'),
        'guide': ('magenta', '📖 指导'),
        'handoff_agent': ('bright_magenta', '🔄 智能体切换'),
        'stage_summary': ('bright_cyan', '📊 阶段总结'),
        'do_subtask': ('bright_yellow', '🎯 子任务'),
        'do_subtask_result': ('green', '🎯 执行结果'),
        'rewrite': ('yellow', '✏️ 重写'),
        'query_suggest': ('bright_magenta', '💡 查询建议'),
        'chunk': ('white', '📦 数据块')
    }
    
    return type_styles.get(message_type, ('white', f'📄 {message_type}'))


class StreamingMessageBox:
    """支持流式输出的消息框类"""
    
    def __init__(self, console, message_type: str, agent_name: str = None):
        self.console = console
        self.message_type = message_type
        self.agent_name = agent_name
        self.type_color, self.type_label = get_message_type_style(message_type)
        self.terminal_width = shutil.get_terminal_size().columns
        self.box_width = min(self.terminal_width - 4, 80)  # 最大80字符，最小留4字符边距
        self.content_width = self.box_width - 4  # 减去边框(2个字符)和空格(2个字符)
        self.current_line = ""
        self.lines: List[str] = []
        self.header_printed = False
        self.last_printed_content = ""
        self.line_started = False  # 标记当前行是否已开始
        
    def _print_header(self):
        """打印消息框头部"""
        if not self.header_printed:
            # 顶部边框
            top_border = "╭" + "─" * (self.box_width - 2) + "╮"
            self.console.print(f"\n[{self.type_color}]{top_border}[/{self.type_color}]")
            
            # 标题行（考虑中文字符宽度）
            display_label = f"{self.type_label} | {self.agent_name}" if self.agent_name else self.type_label
            title_display_width = self._get_display_width(display_label)
            title_padding = self.box_width - 3 - title_display_width  # 减去左边框、左空格、右边框
            if title_padding < 0:
                title_padding = 0
            title_line = f"│ {display_label}{' ' * title_padding}│"
            self.console.print(f"[{self.type_color}]{title_line}[/{self.type_color}]")
            
            # 分隔线
            separator = "├" + "─" * (self.box_width - 2) + "┤"
            self.console.print(f"[{self.type_color}]{separator}[/{self.type_color}]")
            
            self.header_printed = True
    
    def add_content(self, text: str):
        """添加流式内容
        Args:
            text: 要添加的内容。这个内容就是增量的内容
        """
        self._print_header()
        
        # 处理增量内容
        if text:
            # 逐字符处理，检查是否需要换行
            for char in text:
                if char == '\n':
                    # 遇到换行符，完成当前行并开始新行
                    if self.line_started:
                        self._complete_current_line()
                    self.current_line = ""
                    self._start_new_line()
                    self.line_started = True
                else:
                    # 如果还没有开始行，先开始
                    if not self.line_started:
                        self._start_new_line()
                        self.line_started = True
                    
                    # 检查添加这个字符后是否会超出宽度
                    test_line = self.current_line + char
                    if self._get_display_width(test_line) >= self.content_width:
                        # 超出宽度，先完成当前行，然后开始新行
                        self._complete_current_line()
                        self.current_line = ""
                        self._start_new_line()
                        self.line_started = True
                    
                    # 打印字符并添加到当前行
                    self.console.print(char, end="")
                    self.current_line += char
    
    def _start_new_line(self):
        """开始新行，打印行开头"""
        self.console.print(f"[{self.type_color}]│[/{self.type_color}] ", end="")
    
    def _complete_current_line(self):
        """完成当前行，添加填充和行结尾"""
        if self.line_started:
            # 计算当前行的显示宽度
            current_width = self._get_display_width(self.current_line)
            # 计算需要的填充
            padding = self.content_width - current_width
            if padding > 0:
                self.console.print(" " * padding, end="")
            # 打印行结尾
            self.console.print(f"[{self.type_color}] │[/{self.type_color}]")
            self.line_started = False
    
    def _flush_current_line(self):
        """输出完整行（用于非流式输出）"""
        if self.current_line:
            self.lines.append(self.current_line)
            display_width = self._get_display_width(self.current_line)
            padding = self.content_width - display_width
            if padding < 0:
                padding = 0
            line_content = f"[{self.type_color}]│[/{self.type_color}] [white]{self.current_line}[/white]{' ' * padding}[{self.type_color}] │[/{self.type_color}]"
            self.console.print(line_content)
    
    def _get_display_width(self, text: str) -> int:
        """计算文本的实际显示宽度（考虑emoji和中文字符）"""
        import unicodedata
        width = 0
        i = 0
        while i < len(text):
            char = text[i]
            try:
                # 获取字符的East Asian Width属性
                eaw = unicodedata.east_asian_width(char)
                if eaw in ('F', 'W'):  # Fullwidth or Wide
                    width += 2
                elif eaw in ('H', 'Na', 'N'):  # Halfwidth, Narrow, or Neutral
                    width += 1
                else:  # Ambiguous
                    # 对于emoji等特殊字符，使用更精确的判断
                    if ord(char) >= 0x1F000:  # emoji范围
                        width += 2
                    else:
                        width += 1
            except TypeError:
                # 处理复合emoji字符（如🛠️）
                width += 2
            i += 1
        return width
    
    def finish(self):
        """完成消息框，打印底部边框"""
        # 如果有行正在进行中，必须先完成它
        if self.line_started:
            self._complete_current_line()
        
        # 底部边框
        bottom_border = "╰" + "─" * (self.box_width - 2) + "╯"
        self.console.print(f"[{self.type_color}]{bottom_border}[/{self.type_color}]")

def display_items_in_columns(items: List[str], title: str = "", color: str = "cyan"):
    """在终端中以多列形式显示列表项，并确保列对齐和自动添加序号。"""
    if not items:
        console.print(f"[{color}]未检测到可用 {Text.from_markup(title)}[/]")
        return

    if title:
        console.print(f"\n[{color}]📋 {Text.from_markup(title)}(共{len(items)}个)：[/]")

    # 计算最长项的显示宽度
    max_item_display_width = max(Text(item).cell_len for item in items)
    # 序号最大两位数，所以需要2位 + '.' + ' ' = 4位
    index_padding = 4 

    terminal_width = os.get_terminal_size().columns
    
    # 假设列间距为 2 个字符
    column_spacing = 2
    
    # 每列的最小内容宽度，确保能容纳最长项，并设定一个合理的最小值
    min_content_width = max(15, max_item_display_width) 
    
    # 每列的最小总宽度，包括内容、序号和列间距
    min_col_total_width = min_content_width + index_padding + column_spacing
    
    # 计算每行可以容纳的列数
    cols_per_line = max(1, terminal_width // min_col_total_width)
    
    # 如果项目数量少于计算出的列数，则将列数限制为项目数量
    cols_per_line = min(cols_per_line, len(items))

    for i in range(0, len(items), cols_per_line):
        line_items = items[i:i + cols_per_line]
        line_parts = []
        
        for j, item in enumerate(line_items):
            item_text = Text(item)
            # 填充到 min_content_width 宽度，确保内容对齐
            item_text.pad_right(min_content_width - item_text.cell_len)
            
            # 序号格式化，固定为2位，右对齐
            index_str = f"{i + j + 1:2d}."
            
            # 构建完整的列字符串
            formatted_item = f"[yellow]{index_str}[/yellow] [bold]{item_text}[/bold]"
            line_parts.append(formatted_item)
            
        console.print("  ".join(line_parts))

    console.print(f"\n[dim]共加载 {len(items)} 个 {title}[/dim]")