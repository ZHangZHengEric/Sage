"""
针对流式 LLM 输出的简单 XML 风格 tag 判别工具。

仅用于 ``query_suggest_agent`` 这类需要在流式过程中区分"当前 token 属于哪个 tag 内"的场景。
"""

from __future__ import annotations

from typing import List, Optional


def judge_delta_content_type(
    delta_content: str,
    all_tokens_str: str,
    tag_type: Optional[List[str]] = None,
) -> str:
    """根据已累积的 token 串与新 delta，判断当前位置位于哪个 tag 内部。

    返回值：
    - ``"tag"``：当前刚好在标签边界上（开始/结束 tag 本身或 tag 之外）；
    - ``"unknown"``：紧跟在某个开始 tag 后，但当前 buffer 末尾正在拼接潜在的结束 tag 前缀；
    - 标签名（去掉尖括号）：当前位置位于该开始 tag 与对应结束 tag 之间。
    """
    if tag_type is None:
        tag_type = []

    start_tag = [f"<{tag}>" for tag in tag_type]
    end_tag = [f"</{tag}>" for tag in tag_type]

    # 结束标签的所有可能前缀（用于探测半截输出的结束 tag）
    end_tag_process_list: List[str] = []
    for tag in end_tag:
        for i in range(len(tag)):
            end_tag_process_list.append(tag[:i + 1])

    last_tag = None
    last_tag_index: Optional[int] = None

    all_tokens_str = (all_tokens_str + delta_content).strip()

    for tag in start_tag + end_tag:
        index = all_tokens_str.rfind(tag)
        if index != -1:
            if last_tag_index is None or index > last_tag_index:
                last_tag = tag
                last_tag_index = index

    if last_tag is None or last_tag_index is None:
        return "tag"

    if last_tag in start_tag:
        if last_tag_index + len(last_tag) == len(all_tokens_str):
            return 'tag'
        for end_tag_process in end_tag_process_list:
            if all_tokens_str.endswith(end_tag_process):
                return 'unknown'
        return last_tag.replace("<", "").replace(">", "")
    elif last_tag in end_tag:
        return 'tag'

    return "tag"
