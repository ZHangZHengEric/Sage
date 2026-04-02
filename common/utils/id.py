"""ID 生成工具 (shared)."""

import uuid


def gen_id() -> str:
    return uuid.uuid4().hex


def generate_short_id(length: int = 8) -> str:
    """生成短ID"""
    return uuid.uuid4().hex[:length]
