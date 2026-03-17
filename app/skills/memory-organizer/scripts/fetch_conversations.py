#!/usr/bin/env python3
"""
对话获取与压缩脚本
从 Sage 后端 API 获取对话记录，并进行智能压缩输出

关键特性：
- 必须指定 --agent-id 参数
- 只保留：USER 消息 + 该轮次对应的最后一个 ASSISTANT 消息
- 移除所有 TOOL 消息和无用的中间 ASSISTANT 消息
- 移除会话元数据，只保留核心对话内容
- 每条消息带时间戳
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import argparse
from pathlib import Path

def get_sage_base_url() -> str:
    """获取 Sage 后端基础 URL"""
    port = os.environ.get('SAGE_PORT', '51805')
    return f"http://localhost:{port}"

def get_available_agents() -> List[str]:
    """获取所有可用的 Agent ID"""
    sage_root = os.environ.get('SAGE_ROOT', '/Users/zhangzheng/.sage')
    agents_path = Path(sage_root) / 'agents'
    
    if not agents_path.exists():
        return []
    
    agents = []
    for item in agents_path.iterdir():
        if item.is_dir() and item.name.startswith('agent_'):
            agents.append(item.name)
    
    return agents

def fetch_conversations(
    agent_id: str,
    page: int = 1,
    page_size: int = 100,
    sort_by: str = "date",
    days: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    从后端 API 获取指定 Agent 的对话列表
    
    Args:
        agent_id: Agent ID
        page: 页码
        page_size: 每页数量
        sort_by: 排序方式
        days: 最近多少天（与 start_time/end_time 互斥）
        start_time: 开始时间（ISO 格式，如 2024-01-01 或 2024-01-01T00:00:00）
        end_time: 结束时间（ISO 格式，如 2024-01-31 或 2024-01-31T23:59:59）
    """
    base_url = get_sage_base_url()
    url = f"{base_url}/api/conversations"
    
    # 解析时间范围
    if start_time or end_time:
        # 使用指定的时间范围
        if start_time:
            try:
                # 尝试解析完整时间格式
                if 'T' in start_time:
                    start_date = datetime.fromisoformat(start_time.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    # 只有日期，设为当天开始
                    start_date = datetime.strptime(start_time, "%Y-%m-%d")
            except ValueError as e:
                print(f"错误：无法解析开始时间 '{start_time}'，请使用 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS 格式", file=sys.stderr)
                return []
        else:
            start_date = datetime.min
            
        if end_time:
            try:
                # 尝试解析完整时间格式
                if 'T' in end_time:
                    end_date = datetime.fromisoformat(end_time.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    # 只有日期，设为当天结束
                    end_date = datetime.strptime(end_time, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            except ValueError as e:
                print(f"错误：无法解析结束时间 '{end_time}'，请使用 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS 格式", file=sys.stderr)
                return []
        else:
            end_date = datetime.now()
    else:
        # 使用 days 参数
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days or 7)
    
    params = {
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "agent_id": agent_id
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 200:
            print(f"Error: {data.get('message', 'Unknown error')}", file=sys.stderr)
            return []
        
        conversations = data.get("data", {}).get("list", [])
        
        filtered_conversations = []
        for conv in conversations:
            conv_date = conv.get("updated_at") or conv.get("created_at")
            if conv_date:
                try:
                    if isinstance(conv_date, str):
                        conv_datetime = datetime.fromisoformat(conv_date.replace('Z', '+00:00'))
                    else:
                        conv_datetime = datetime.fromtimestamp(conv_date)
                    
                    if start_date <= conv_datetime.replace(tzinfo=None) <= end_date:
                        filtered_conversations.append(conv)
                except:
                    filtered_conversations.append(conv)
            else:
                filtered_conversations.append(conv)
        
        return filtered_conversations
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching conversations for agent {agent_id}: {e}", file=sys.stderr)
        return []

def fetch_messages(session_id: str) -> List[Dict[str, Any]]:
    """获取指定会话的所有消息"""
    base_url = get_sage_base_url()
    url = f"{base_url}/api/conversations/{session_id}/messages"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 200:
            return []
        
        return data.get("data", {}).get("messages", [])
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching messages for session {session_id}: {e}", file=sys.stderr)
        return []

def compress_assistant_message(content: str) -> str:
    """压缩 Assistant 消息，只保留关键行动和结论"""
    lines = content.split('\n')
    
    key_patterns = [
        "执行", "完成", "创建", "修改", "更新", "删除", "读取", "写入",
        "决定", "选择", "分析", "结论", "结果", "成功", "失败",
        "错误", "异常", "警告", "注意", "建议", "推荐",
        "下一步", "待办", "需要", "应该", "可以",
        "文件", "路径", "代码", "脚本", "函数", "类",
        "API", "接口", "请求", "响应", "数据",
        "安装", "配置", "部署", "运行", "测试", "验证",
        "用户", "记住", "记录", "保存", "提取"
    ]
    
    compressed_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if any(pattern in line for pattern in key_patterns):
            compressed_lines.append(line)
        elif len(line) < 80 and any(word in line for word in ["因此", "所以", "总之", "总结", "结论", "看来", "似乎", "可能", "已"]):
            compressed_lines.append(line)
        elif any(word in line for word in ["调用", "使用", "执行", "运行", "启动", "生成"]):
            compressed_lines.append(line)
    
    if compressed_lines:
        unique_lines = list(dict.fromkeys(compressed_lines))
        return " | ".join(unique_lines[:5])
    else:
        word_count = len(content.split())
        return f"已执行操作（约{word_count}字）"

def format_timestamp(timestamp) -> str:
    """格式化时间戳"""
    if not timestamp:
        return "未知时间"
    
    if isinstance(timestamp, (int, float)):
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            return str(timestamp)
    elif isinstance(timestamp, str):
        try:
            if 'T' in timestamp:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass
        return timestamp
    
    return str(timestamp)

def compress_conversation_messages(messages: List[Dict[str, Any]]) -> List[str]:
    """
    压缩会话消息，只保留核心对话：
    - 每个 USER 消息
    - 该 USER 对应的最后一个 ASSISTANT 消息
    - 移除所有 TOOL 消息和中间 ASSISTANT 消息
    """
    if not messages:
        return ["  [无消息记录]"]
    
    # 过滤出只保留 USER 和 ASSISTANT 消息
    filtered_messages = []
    for msg in messages:
        role = msg.get("role", "")
        if role in ["user", "assistant"]:
            filtered_messages.append(msg)
    
    if not filtered_messages:
        return ["  [无用户或助手消息]"]
    
    # 构建对话轮次：USER -> 最后一个 ASSISTANT
    output_lines = []
    i = 0
    
    while i < len(filtered_messages):
        msg = filtered_messages[i]
        role = msg.get("role", "")
        
        if role == "user":
            timestamp = format_timestamp(msg.get("timestamp"))
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            
            # 添加 USER 消息
            output_lines.append(f"  [{timestamp}] 用户：{content}")
            
            # 找到下一个 ASSISTANT 消息（跳过中间的）
            j = i + 1
            last_assistant_idx = -1
            
            while j < len(filtered_messages):
                if filtered_messages[j].get("role") == "assistant":
                    last_assistant_idx = j
                j += 1
            
            # 添加最后一个 ASSISTANT 消息
            if last_assistant_idx > 0:
                assistant_msg = filtered_messages[last_assistant_idx]
                timestamp = format_timestamp(assistant_msg.get("timestamp"))
                content = assistant_msg.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                
                # 压缩 ASSISTANT 消息
                compressed = compress_assistant_message(content)
                output_lines.append(f"  [{timestamp}] 助手：{compressed}")
            
            # 移动到下一个 USER
            if last_assistant_idx > 0:
                i = last_assistant_idx + 1
            else:
                i += 1
        else:
            i += 1
    
    return output_lines if output_lines else ["  [无有效对话]"]

def process_conversations(
    conversations: List[Dict[str, Any]],
    agent_id: str,
    days: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> str:
    """处理所有对话，生成精简的输出"""
    output_lines = []
    
    # 构建标题
    if start_time or end_time:
        time_range = f"{start_time or '开始'} 至 {end_time or '现在'}"
        output_lines.append(f"=== Agent {agent_id} - {time_range} 对话 ===")
    else:
        output_lines.append(f"=== Agent {agent_id} - 最近 {days or 7} 天对话 ===")
    
    output_lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    output_lines.append("")
    
    total_conversations = len(conversations)
    total_user_messages = 0
    total_assistant_messages = 0
    
    for idx, conv in enumerate(conversations, 1):
        title = conv.get("title", "无标题")[:60]  # 限制标题长度
        session_id = conv.get("session_id") or conv.get("id")
        
        # 获取并压缩消息
        messages = fetch_messages(session_id)
        if not messages:
            continue
        
        compressed_msgs = compress_conversation_messages(messages)
        
        if len(compressed_msgs) <= 1 and "无" in compressed_msgs[0]:
            continue
        
        # 添加会话标题和消息
        output_lines.append(f"--- {title} ---")
        output_lines.extend(compressed_msgs)
        output_lines.append("")
        
        # 统计
        total_user_messages += sum(1 for m in messages if m.get("role") == "user")
        total_assistant_messages += sum(1 for m in messages if m.get("role") == "assistant")
    
    # 统计信息
    output_lines.append(f"=== 统计 ===")
    output_lines.append(f"对话数：{total_conversations}")
    output_lines.append(f"用户消息：{total_user_messages}")
    output_lines.append(f"助手消息：{total_assistant_messages}")
    output_lines.append(f"提示：此输出用于后续可能的记忆提取，非强制整理。")
    
    return "\n".join(output_lines)

def main():
    parser = argparse.ArgumentParser(
        description="获取并压缩 Sage Agent 对话记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 查看可用的 Agent ID
  python fetch_conversations.py --list-agents
  
  # 获取最近 7 天的对话（必须指定 agent-id）
  python fetch_conversations.py --agent-id agent_93905d3d --days 7
  
  # 获取指定时间范围的对话
  python fetch_conversations.py --agent-id agent_93905d3d --start-time 2024-01-01 --end-time 2024-01-31
  
  # 获取从某时开始到最近的对话
  python fetch_conversations.py --agent-id agent_93905d3d --start-time 2024-01-01T00:00:00
  
  # 保存到文件
  python fetch_conversations.py --agent-id agent_93905d3d --days 7 --output /tmp/conversations.txt
        """
    )
    
    parser.add_argument("--list-agents", action="store_true",
                       help="列出所有可用的 Agent ID")
    parser.add_argument("--agent-id", type=str, 
                       help="Agent ID。使用 --list-agents 查看可用的 Agent ID")
    parser.add_argument("--days", type=int, 
                       help="获取最近多少天的对话 (与 --start-time/--end-time 互斥)")
    parser.add_argument("--start-time", type=str,
                       help="开始时间 (格式: YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS)")
    parser.add_argument("--end-time", type=str,
                       help="结束时间 (格式: YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS)")
    parser.add_argument("--page", type=int, default=1, 
                       help="页码 (默认：1)")
    parser.add_argument("--page-size", type=int, default=100, 
                       help="每页数量 (默认：100, 最大：100)")
    parser.add_argument("--sort-by", type=str, default="date", 
                       choices=["date", "title", "messages"], 
                       help="排序方式 (默认：date)")
    parser.add_argument("--output", type=str, 
                       help="输出文件路径 (默认：输出到 stdout)")
    
    args = parser.parse_args()
    
    # 列出可用 Agent
    if args.list_agents:
        agents = get_available_agents()
        if agents:
            print("可用的 Agent ID:")
            for agent in agents:
                print(f"  - {agent}")
        else:
            print("未找到任何 Agent")
        sys.exit(0)
    
    # 验证 agent_id
    if not args.agent_id:
        print("错误：必须指定 --agent-id 参数", file=sys.stderr)
        print("\n使用 --list-agents 查看可用的 Agent ID", file=sys.stderr)
        sys.exit(1)

    available_agents = get_available_agents()
    if args.agent_id not in available_agents:
        print(f"错误：Agent ID '{args.agent_id}' 不存在", file=sys.stderr)
        print(f"\n可用的 Agent ID:", file=sys.stderr)
        for agent in available_agents:
            print(f"  - {agent}", file=sys.stderr)
        sys.exit(1)

    # 验证时间参数
    if (args.start_time or args.end_time) and args.days:
        print("错误：--days 与 --start-time/--end-time 参数互斥，不能同时使用", file=sys.stderr)
        sys.exit(1)

    # 构建提示信息
    if args.start_time or args.end_time:
        time_range = f"{args.start_time or '开始'} 至 {args.end_time or '现在'}"
        print(f"正在获取 Agent '{args.agent_id}' {time_range} 的对话...", file=sys.stderr)
    else:
        days = args.days or 7
        print(f"正在获取 Agent '{args.agent_id}' 最近 {days} 天的对话...", file=sys.stderr)

    # 获取对话
    conversations = fetch_conversations(
        agent_id=args.agent_id,
        page=args.page,
        page_size=min(args.page_size, 100),
        sort_by=args.sort_by,
        days=args.days,
        start_time=args.start_time,
        end_time=args.end_time
    )

    if not conversations:
        print(f"未找到符合条件的对话记录", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(conversations)} 条对话记录", file=sys.stderr)

    # 处理并压缩
    compressed_output = process_conversations(conversations, args.agent_id, args.days, args.start_time, args.end_time)
    
    # 输出
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(compressed_output)
        print(f"已保存到：{args.output}", file=sys.stderr)
    else:
        print(compressed_output)

if __name__ == "__main__":
    main()