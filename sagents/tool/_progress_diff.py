"""progress 通道的 tail 增量计算工具。

抽到独立模块以便单测无需触发 ``execute_command_tool`` 的沉重 import 链。
"""

from __future__ import annotations


def diff_tail_for_progress(prev: str, cur: str) -> str:
    """计算从 ``prev`` 到 ``cur`` 的新增部分用于 progress 推送。

    沙箱 ``read_background_output`` 通常返回 tail（受 max_bytes 限制），
    随着新输出到来 tail 整体右移；这里用 ``cur`` 的尾部相对 ``prev`` 的
    新增片段作为 delta。

    策略：
    - 若 ``prev`` 是 ``cur`` 的前缀，返回 ``cur[len(prev):]``（最常见）。
    - 否则（沙箱 tail 已截断旧字节），尝试在 ``cur`` 中找 ``prev`` 末尾
      ~512 字节的位置，从其之后输出；找不到则把 ``cur`` 整体作为 delta
      返回（极少数边界场景，可能会重复输出一段，可接受）。
    """
    if not cur:
        return ""
    if not prev:
        return cur
    if cur.startswith(prev):
        return cur[len(prev):]
    # 沙箱 tail 已截断旧字节：找 cur 的开头与 prev 的末尾的最长重叠 k，
    # 使 prev.endswith(cur[:k])。窗口最大限制 512 字符。
    max_overlap = min(len(prev), len(cur), 512)
    for k in range(max_overlap, 0, -1):
        if prev.endswith(cur[:k]):
            return cur[k:]
    return cur


__all__ = ["diff_tail_for_progress"]
