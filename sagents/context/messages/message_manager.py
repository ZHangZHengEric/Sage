"""
MessageManager 优化版消息管理器

专门管理非system消息，提供完整的消息管理功能：
- 增加message chunk
- 增加完整message
- 合并message (参考agent_base.py实现)
- 过滤和压缩消息
- 获取所有消息

注意：此类不处理system消息，所有system消息会被过滤掉

作者: Eric ZZ
版本: 2.0 (优化版)
"""

import datetime
import json
import time
import re
import uuid
from collections import OrderedDict
import threading
from typing import Dict, List, Optional, Any, Union, Sequence, Tuple, TypeVar
from copy import deepcopy
from dataclasses import replace
from sagents.utils.logger import logger
from sagents.context.messages.context_budget import ContextBudgetManager
from .message import MessageRole, MessageType, MessageChunk
from .token_accounting import (
    ContextViewSpec,
    DEFAULT_COMPRESSION_THRESHOLD,
    InferenceViewTokenReport,
    PromptTokenEstimator,
)

# 全局动态 token 比例计算（所有 MessageManager 实例共享）
_global_token_ratio_samples: List[Dict[str, float]] = []  # 存储字符数和token数的样本
_global_max_ratio_samples = 10  # 最多保留10个样本
_global_default_token_ratio = 0.4  # 默认比例（中文约0.6，英文约0.25，混合约0.4）
_max_base64_image_token_estimate = 3000  # base64 图片 token 估算上限
_message_token_estimate_cache: "OrderedDict[str, int]" = OrderedDict()
_message_token_estimate_cache_limit = 2048
_message_token_estimate_cache_lock = threading.Lock()

# 协议性状态工具：可持久化在 messages.json，但不参与发往 LLM 的 tool_calls/tool 对（见 strip_turn_status_from_llm_context）
TURN_STATUS_TOOL_NAME = "turn_status"
SEARCH_MEMORY_TOOL_NAME = "search_memory"
COMPRESS_HISTORY_TOOL_NAME = "compress_conversation_history"
TODO_WRITE_TOOL_NAME = "todo_write"
DEFAULT_LLM_PROTECTION_COUNT = 12

MessageItemT = TypeVar("MessageItemT", bound=Union[MessageChunk, Dict[str, Any]])


class MessageManager:
    """
    优化版消息管理器

    专门管理非system消息，提供完整的消息管理功能。
    不允许保存system消息，所有system消息会被自动过滤。
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        max_token_limit: int = 8000,
        compression_threshold: float = DEFAULT_COMPRESSION_THRESHOLD,
        context_budget_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化消息管理器

        Args:
            session_id: 会话ID
            max_token_limit: 最大token限制
            compression_threshold: 压缩阈值
            context_budget_config: 上下文预算管理器配置，包含以下键：
                - max_model_len: 模型最大token长度，默认 40000
                - history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
                - active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
                - max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_token_limit = max_token_limit
        if (
            context_budget_config is not None
            and context_budget_config.get("compression_threshold") is not None
        ):
            compression_threshold = float(
                context_budget_config["compression_threshold"]
            )
        if not 0 < float(compression_threshold) < 1:
            raise ValueError(
                "compression_threshold must be greater than 0 and less than 1"
            )
        self.compression_threshold = float(compression_threshold)

        if context_budget_config is None:
            context_budget_config = {}

        self.context_budget_manager = ContextBudgetManager(
            max_model_len=context_budget_config.get("max_model_len") or 40000,
            history_ratio=context_budget_config.get("history_ratio") or 0.2,
            active_ratio=context_budget_config.get("active_ratio") or 0.3,
            max_new_message_ratio=context_budget_config.get("max_new_message_ratio")
            or 0.5,
        )

        # 消息存储（只存储非system消息）
        self.messages: List[MessageChunk] = []
        # 最近一次发往 LLM 前构造出的 inference view。
        # self.messages 始终是原始 ledger；推理视图只隐藏已被有效摘要覆盖的历史。
        self.inference_messages: List[MessageChunk] = []
        # 从 compression anchors 派生的调试/审计索引，不作为推理真相源。
        self.compact_manifest: Dict[str, Any] = {}

        # 兼容性：保留pending_chunks属性（现在已不使用）
        self.pending_chunks: List[Any] = []

        self.active_start_index: Optional[int] = None

        # 统计信息
        self.stats: Dict[str, Any] = {
            "total_messages": 0,
            "total_chunks": 0,
            "merged_messages": 0,
            "filtered_messages": 0,
            "compressed_messages": 0,
            "system_messages_rejected": 0,
            "duplicate_content_rejected": 0,
            "created_at": datetime.datetime.now().isoformat(),
            "last_updated": datetime.datetime.now().isoformat(),
        }

        # 跨 Agent 调用的签名历史（用于检测循环模式）
        # 存储最近几轮 SimpleAgent 执行的签名，支持跨调用检测 AAAA/ABAB 等模式
        self._recent_loop_signatures: List[str] = []
        self._max_loop_signatures = 24  # 保留最近24个签名

    def update_messages(
        self, messages: Union[MessageChunk, List[MessageChunk]]
    ) -> None:
        """
        根据message 的id 来更新消息列表

        Args:
            messages: 消息列表
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]
        for message in messages:
            for i, old_message in enumerate(self.messages):
                if old_message.message_id == message.message_id:
                    self.messages[i] = message
                    break

    def store_inference_messages(self, messages: List[MessageChunk]) -> None:
        """保存最近一次推理视图快照，不影响原始消息 ledger。"""
        self.inference_messages = deepcopy(messages)

    def set_active_start_index(self, index: Optional[int]) -> None:
        """
        设置活跃消息的起始索引

        活跃消息指的是固定加入上下文的连续对话，从此索引开始的消息将被视为活跃消息。
        索引之前的消息将被视为历史消息，可用于相似度检索。

        Args:
            index: 活跃消息的起始索引，None表示所有消息都是活跃消息
        """
        previous_index = self.active_start_index
        self.active_start_index = index
        if previous_index != index:
            logger.debug(
                f"MessageManager: 设置 active_start_index = {index}，"
                f"历史消息: {index if index else 0}条，"
                f"活跃消息: {len(self.messages) - (index if index else 0)}条"
            )

    def prepare_history_split(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """计算 token 预算并刷新历史锚点。

        说明：active_start_index 不再由 token budget 驱动（避免在 LLM 上下文层做硬截断）。
        其语义已变更为：指向"最近一次成功 compress_conversation_history anchor"的位置，
        仅供 memory 工具划定 RAG 检索范围使用；没有压缩调用时为 None。
        本方法保留以维持 budget_info 计算（多个辅助 Agent 仍依赖它做局部规则压缩）。
        """
        budget_info = self.context_budget_manager.calculate_budget(agent_config)
        self._refresh_history_anchor_index()
        return {"budget_info": budget_info}

    def compute_history_anchor_index(self) -> Optional[int]:
        """扫描 self.messages 找到最近一次成功 compression anchor 的位置。

        Returns:
            该 Assistant 调用消息的索引；未找到时返回 None。
            索引之前的消息视为"已被工具总结过的历史"，可作为 memory 检索范围；
            索引及之后的消息（含工具结果）视为活跃段。
        """
        pairs = MessageManager._expanded_compression_pairs(self.messages)
        visible_pairs = [pair for pair in pairs if not pair.get("covered_by_later")]
        if not visible_pairs:
            return None
        return max(pair["assistant_idx"] for pair in visible_pairs)
        return None

    def _refresh_history_anchor_index(self) -> None:
        """根据最新成功 compression anchor 位置刷新 active_start_index（仅供 memory 使用）。"""
        self.refresh_compact_manifest()
        self.set_active_start_index(self.compute_history_anchor_index())

    def refresh_compact_manifest(self) -> Dict[str, Any]:
        """刷新 compact manifest；manifest 只从 self.messages 派生。"""
        self.compact_manifest = MessageManager.build_compact_manifest(self.messages)
        return self.compact_manifest

    def get_compact_manifest(self) -> Dict[str, Any]:
        """返回最新 compact manifest，便于保存和调试。"""
        return self.refresh_compact_manifest()

    def get_recent_loop_signatures(self) -> List[str]:
        """
        获取最近的循环签名历史

        供 SimpleAgent 在 _execute_loop 开始时加载历史签名

        Returns:
            List[str]: 最近的签名列表
        """
        return self._recent_loop_signatures.copy()

    def add_loop_signature(self, signature: str) -> None:
        """
        添加循环签名到历史记录

        供 SimpleAgent 在每轮执行后记录签名

        Args:
            signature: 签名字符串
        """
        self._recent_loop_signatures.append(signature)

        # 限制列表大小，避免内存无限增长
        if len(self._recent_loop_signatures) > self._max_loop_signatures:
            self._recent_loop_signatures = self._recent_loop_signatures[
                -self._max_loop_signatures :
            ]

    def clear_loop_signatures(self) -> None:
        """
        清除循环签名历史

        在会话重置或需要重新开始检测时调用
        """
        self._recent_loop_signatures.clear()

    def add_messages(
        self,
        messages: Union[MessageChunk, List[MessageChunk]],
        agent_name: Optional[str] = None,
    ) -> bool:
        """
        添加消息或消息列表

        Args:
            messages: 消息实例或消息列表
            agent_name: 智能体名称
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]

        for message in messages:
            try:
                # 过滤system消息
                if message.role == MessageRole.SYSTEM.value:
                    self.stats["system_messages_rejected"] += 1
                    continue
                # 过滤 content、reasoning_content 以及 tool_calls 都为空的消息
                if (
                    not message.content
                    and not message.reasoning_content
                    and not message.tool_calls
                ):
                    self.stats["filtered_messages"] += 1
                    continue
            except Exception:
                logger.error(f"MessageManager: 添加消息失败，消息内容: {message}")
                continue

            self.messages = MessageManager.merge_new_message_old_messages(
                message, self.messages
            )

        self.stats["total_messages"] = len(self.messages)
        self.stats["total_chunks"] += len(messages)
        self.stats["last_updated"] = datetime.datetime.now().isoformat()

        # 新消息可能包含 compress_conversation_history 工具调用，刷新锚点
        self._refresh_history_anchor_index()
        return True

    @staticmethod
    def merge_new_messages_to_old_messages(
        new_messages: List[Union[MessageChunk, Dict]],
        old_messages: List[Union[MessageChunk, Dict]],
    ) -> List[MessageChunk]:
        """
        合并新消息列表和旧消息列表

        Args:
            new_messages: 新消息列表
            old_messages: 旧消息列表
        """
        new_messages_chunks = [
            MessageChunk.from_dict(msg) if isinstance(msg, dict) else msg
            for msg in new_messages
        ]
        old_messages_chunks = [
            MessageChunk.from_dict(msg) if isinstance(msg, dict) else msg
            for msg in old_messages
        ]
        for new_message in new_messages_chunks:
            old_messages_chunks = MessageManager.merge_new_message_old_messages(
                new_message, old_messages_chunks
            )

        # Auto-generated compression messages are emitted during a running
        # SimpleAgent loop. A normal streaming merge appends them to the current
        # turn, which changes chronology on the next provider request. Relocate a
        # completed successful pair to its source boundary, matching the durable
        # ledger layout.
        for result in new_messages_chunks:
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            if not MessageManager._is_successful_compression_result(result):
                continue
            source_end = metadata.get("source_end_message_id")
            if not source_end or not result.tool_call_id:
                continue
            assistant = next(
                (
                    message
                    for message in old_messages_chunks
                    if message.role == MessageRole.ASSISTANT.value
                    and result.tool_call_id
                    in MessageManager._tool_result_ids_for_assistant(message)
                ),
                None,
            )
            if assistant is None:
                continue
            pair_ids = {
                message_id
                for message_id in (assistant.message_id, result.message_id)
                if message_id
            }
            without_pair = [
                message
                for message in old_messages_chunks
                if message.message_id not in pair_ids
            ]
            source_index = next(
                (
                    idx
                    for idx, message in enumerate(without_pair)
                    if message.message_id == source_end
                ),
                None,
            )
            if source_index is None:
                continue
            old_messages_chunks = (
                without_pair[: source_index + 1]
                + [assistant, result]
                + without_pair[source_index + 1 :]
            )
        return old_messages_chunks

    @staticmethod
    def calculate_messages_token_length(
        messages: Sequence[Union[MessageChunk, Dict]],
    ) -> int:
        """
        计算消息列表的 token 长度，同时计算 content 与 reasoning_content。
        优先使用动态比例计算，如果没有样本则使用静态规则

        Args:
            messages: 消息列表

        Returns:
            int: 消息列表的token长度
        """
        # 如果有动态比例样本，优先使用动态计算
        if _global_token_ratio_samples:
            return MessageManager._calculate_messages_token_length_dynamic(messages)

        # 否则使用静态规则计算
        token_length = 0
        for message in messages:
            token_length += MessageManager.calculate_message_token_length(message)

        return token_length

    @staticmethod
    def calculate_message_token_length(
        message: Union[MessageChunk, Dict[str, Any]],
    ) -> int:
        """Estimate both visible content and model-native reasoning content."""
        if isinstance(message, dict):
            message = MessageChunk.from_dict(message)
        return MessageManager.calculate_str_token_length(
            message.get_content()
        ) + MessageManager.calculate_str_token_length(message.reasoning_content)

    @staticmethod
    def _normalize_view_spec(
        view_spec: Optional[Union[ContextViewSpec, Dict[str, Any]]],
    ) -> ContextViewSpec:
        if view_spec is None:
            return ContextViewSpec()
        if isinstance(view_spec, ContextViewSpec):
            return view_spec
        if not isinstance(view_spec, dict):
            raise TypeError("view_spec must be ContextViewSpec, dict, or None")
        return ContextViewSpec(
            policy_id=str(view_spec.get("policy_id") or "default"),
            recent_turns=max(0, int(view_spec.get("recent_turns") or 0)),
            allowed_message_types=tuple(view_spec.get("allowed_message_types") or ()),
            include_compression_anchors=bool(
                view_spec.get("include_compression_anchors", True)
            ),
            protected_message_ids=tuple(
                str(item) for item in view_spec.get("protected_message_ids", ())
            ),
            persistent_history=bool(view_spec.get("persistent_history", False)),
        )

    @staticmethod
    def measure_inference_view(
        messages: Sequence[Union[MessageChunk, Dict[str, Any]]],
        view_spec: Optional[Union[ContextViewSpec, Dict[str, Any]]] = None,
        through_message_id: Optional[str] = None,
        model_identity: Optional[str] = None,
    ) -> InferenceViewTokenReport:
        """Measure a concrete inference view and return per-message estimates.

        Cumulative values are estimates for this exact view, never provider usage.
        Provider usage is request-scoped and is managed by ``PromptBudgetManager``.
        """
        spec = MessageManager._normalize_view_spec(view_spec)
        chunks = [
            MessageChunk.from_dict(item) if isinstance(item, dict) else item
            for item in messages
        ]
        view = MessageManager.build_inference_view(list(chunks))

        if not spec.include_compression_anchors:
            view = [
                item
                for item in view
                if not MessageManager._is_compress_history_tool_call(item)
                and not MessageManager._is_successful_compression_result(item)
            ]
        if spec.allowed_message_types:
            allowed = set(spec.allowed_message_types)
            view = [
                item
                for item in view
                if item.role == MessageRole.USER.value
                or item.normalized_message_type() in allowed
            ]
        if spec.recent_turns > 0:
            user_indices = [
                idx
                for idx, item in enumerate(view)
                if item.role == MessageRole.USER.value
            ]
            if len(user_indices) > spec.recent_turns:
                view = view[user_indices[-spec.recent_turns] :]

        report_messages: List[Dict[str, Any]] = []
        cumulative = 0
        model_key = str(model_identity or "default")
        for item in view:
            provider_message = MessageManager.convert_message_to_dict_for_request(item)
            if provider_message is None:
                continue
            component = PromptTokenEstimator.component(
                "system" if item.role == MessageRole.SYSTEM.value else "message",
                provider_message,
                message_id=item.message_id,
            )
            cache_key = f"{model_key}:{component.fingerprint}"
            with _message_token_estimate_cache_lock:
                cached = _message_token_estimate_cache.get(cache_key)
                if cached is None:
                    cached = component.estimated_tokens
                    _message_token_estimate_cache[cache_key] = cached
                    if (
                        len(_message_token_estimate_cache)
                        > _message_token_estimate_cache_limit
                    ):
                        _message_token_estimate_cache.popitem(last=False)
                else:
                    _message_token_estimate_cache.move_to_end(cache_key)
            cumulative += cached
            report_messages.append(
                {
                    "message_id": item.message_id,
                    "fingerprint": component.fingerprint,
                    "estimated_tokens": cached,
                    "cumulative_estimated_tokens": cumulative,
                }
            )
            if through_message_id and item.message_id == through_message_id:
                break

        return {
            "view_spec_hash": spec.fingerprint(),
            "messages": report_messages,
            "total_estimated_tokens": cumulative,
        }

    @staticmethod
    def calculate_message_token_components(
        messages: Sequence[Union[MessageChunk, Dict]],
    ) -> Dict[str, int]:
        """
        使用与动态 token 估算一致的口径统计消息文本字符数和图片 token。

        这个函数同时用于预估和真实 usage 回灌，避免 ratio 更新和下一轮估算使用
        不同的字符统计口径。
        """
        text_chars = 0
        image_tokens = 0
        image_count = 0

        for message in messages:
            if isinstance(message, dict):
                message = MessageChunk.from_dict(message)
            content = message.get_content()

            reasoning_content = message.reasoning_content
            if isinstance(reasoning_content, str):
                text_chars += len(reasoning_content)

            if isinstance(content, str):
                text_chars += len(content)
            elif isinstance(content, list):
                for item in content:  # pyright: ignore[reportGeneralTypeIssues]
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text":
                        text_chars += len(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        image_count += 1
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                        else:
                            url = str(image_url)
                        if url.startswith("data:"):
                            base64_data = url.split(",")[-1] if "," in url else url
                            estimated = max(500, int(len(base64_data) * 0.2))
                            image_tokens += min(
                                estimated, _max_base64_image_token_estimate
                            )
                        else:
                            image_tokens += 1000

        return {
            "text_chars": text_chars,
            "image_tokens": image_tokens,
            "image_count": image_count,
        }

    @staticmethod
    def _calculate_str_token_length_static(content: str) -> int:
        """
        使用静态规则计算字符串的token长度
        一个中文等于0.6 个token，
        一个英文等于0.25个token，
        一个数字等于0.2 token
        其他符号等于0.4 token

        Args:
            content: 字符串内容

        Returns:
            int: 字符串的token长度
        """
        # 处理None或空字符串的情况
        if not content:
            return 0

        token_length = 0.0
        for char in content:
            # 判断是否是中文字符 (CJK统一表意文字)
            if "\u4e00" <= char <= "\u9fff":
                token_length += 0.6
            elif char.isalpha():
                token_length += 0.25
            elif char.isdigit():
                token_length += 0.2
            else:
                token_length += 0.4
        return int(token_length)

    @staticmethod
    def _extract_text_from_content(
        content: Union[str, List[Dict[str, Any]], None],
    ) -> str:
        """
        从消息内容中提取文本
        支持多模态消息格式

        Args:
            content: 字符串或多模态列表

        Returns:
            str: 提取的文本内容
        """
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            # 从多模态列表中提取文本内容
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return " ".join(text_parts)

        return str(content)

    @staticmethod
    def calculate_str_token_length(
        content: Union[str, List[Dict[str, Any]], None],
    ) -> int:
        """
        计算字符串的token长度（公共静态方法）
        优先使用动态比例，如果没有样本则使用静态规则
        支持多模态消息格式（包含图片token估算）

        Args:
            content: 字符串内容或多模态列表

        Returns:
            int: 字符串的token长度
        """
        # 处理多模态消息格式
        if isinstance(content, list):
            total_tokens = 0
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        # 文本内容
                        text = item.get("text", "")
                        total_tokens += MessageManager._calculate_text_token_length(
                            text
                        )
                    elif item.get("type") == "image_url":
                        # 图片内容 - 估算token
                        # 对于 base64 图片，根据数据长度估算
                        # 通常一张 512x512 的图片大约需要 1000-2000 tokens
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                        else:
                            url = str(image_url)

                        if url.startswith("data:"):
                            # base64 图片：根据数据长度估算
                            # base64 每4个字符 = 3字节，大约 0.75 token/字符
                            base64_data = url.split(",")[-1] if "," in url else url
                            # 估算：base64长度 / 4 * 3 ≈ 原始字节数，再按一定比例算token
                            estimated_tokens = max(500, int(len(base64_data) * 0.2))
                            total_tokens += min(
                                estimated_tokens, _max_base64_image_token_estimate
                            )
                        else:
                            # 远程URL：估算为固定值
                            total_tokens += 1000
            return total_tokens

        # 纯文本内容
        return MessageManager._calculate_text_token_length(content)

    @staticmethod
    def _calculate_text_token_length(text: Union[str, None]) -> int:
        """
        计算文本的token长度

        Args:
            text: 文本内容

        Returns:
            int: token长度
        """
        if not text:
            return 0

        text_str = str(text)

        # 如果有动态比例样本，使用动态比例
        if _global_token_ratio_samples:
            ratio = MessageManager.get_dynamic_token_ratio()
            return int(len(text_str) * ratio)

        # 否则使用静态规则
        return MessageManager._calculate_str_token_length_static(text_str)

    def update_token_ratio(
        self, char_count: int, actual_token_count: int, image_token_count: int = 0
    ) -> None:
        """
        根据实际的 LLM 响应更新 token 比例

        Args:
            char_count: 字符数（输入+输出的总字符数）
            actual_token_count: 实际的 prompt token 数（从 LLM 响应中获取）
            image_token_count: 用同一估算口径得到的图片 token，用于从 prompt token 中扣除
        """
        if char_count <= 0 or actual_token_count <= 0:
            return

        text_token_count = max(0, actual_token_count - max(0, image_token_count))
        if text_token_count <= 0:
            return

        ratio = text_token_count / char_count

        # 添加到全局样本列表
        global _global_token_ratio_samples
        _global_token_ratio_samples.append(
            {
                "char_count": char_count,
                "token_count": text_token_count,
                "ratio": ratio,
                "timestamp": time.time(),
            }
        )

        # 限制样本数量
        if len(_global_token_ratio_samples) > _global_max_ratio_samples:
            _global_token_ratio_samples.pop(0)

    @staticmethod
    def get_dynamic_token_ratio() -> float:
        """
        获取动态的 token 比例（静态方法，所有实例共享）

        Returns:
            float: 基于历史样本的平均 token 比例，如果没有样本则返回默认值
        """
        global _global_token_ratio_samples, _global_default_token_ratio

        if not _global_token_ratio_samples:
            return _global_default_token_ratio

        # 使用最后一次真实请求的比例。prompt usage 是最可信来源，
        # 加权平均会把旧样本带入下一轮，导致长上下文场景收敛过慢。
        avg_ratio = _global_token_ratio_samples[-1]["ratio"]

        # 限制在合理范围内（防止异常值）
        avg_ratio = max(0.1, min(1.0, avg_ratio))

        return avg_ratio

    @staticmethod
    def _calculate_messages_token_length_dynamic(
        messages: Sequence[Union[MessageChunk, Dict]],
    ) -> int:
        """
        使用动态比例计算消息列表的 token 长度（静态方法）
        注意：动态比例只适用于文本内容，图片使用固定估算

        Args:
            messages: 消息列表

        Returns:
            int: 估算的 token 长度
        """
        ratio = MessageManager.get_dynamic_token_ratio()
        components = MessageManager.calculate_message_token_components(messages)
        image_tokens = components["image_tokens"]

        # 文本使用动态比例，图片使用固定估算
        text_chars = components["text_chars"]
        text_tokens = int(text_chars * ratio)
        estimated_tokens = text_tokens + image_tokens
        return estimated_tokens

    @staticmethod
    def merge_new_message_old_messages(
        new_message: MessageChunk, old_messages: List[MessageChunk]
    ) -> List[MessageChunk]:
        """
        合并新消息和旧消息

        Args:
            new_message: 新消息
            old_messages: 旧消息列表

        Returns:
            合并后的消息列表
        """
        old_messages = deepcopy(old_messages)
        new_message_id = new_message.message_id
        # 有new_message_id，查找是否已存在相同message_id的消息，如果old最后一个相同则认为找到，否则认为没有找到
        existing_message = (
            old_messages[-1]
            if old_messages and old_messages[-1].message_id == new_message_id
            else None
        )

        def _tool_call_to_dict(tc):
            if isinstance(tc, dict):
                return deepcopy(tc)
            return {
                "id": getattr(tc, "id", "") or "",
                "index": getattr(tc, "index", None),
                "type": getattr(tc, "type", "function") or "function",
                "function": {
                    "name": getattr(getattr(tc, "function", None), "name", "") or "",
                    "arguments": getattr(getattr(tc, "function", None), "arguments", "")
                    or "",
                },
            }

        if existing_message:
            # 流式消息的特点是每次传递的都是新的增量内容
            if new_message.content is not None:
                # 处理多模态消息格式 - 只对纯文本消息进行合并
                if isinstance(existing_message.content, list) or isinstance(
                    new_message.content, list
                ):
                    # 多模态消息不合并，直接替换
                    existing_message.content = new_message.content
                else:
                    existing_message.content = (
                        existing_message.content or ""
                    ) + new_message.content

            if new_message.reasoning_content is not None:
                existing_message.reasoning_content = (
                    existing_message.reasoning_content or ""
                ) + new_message.reasoning_content

            # reasoning/content/tool_calls are fields of one assistant response.
            # The first streamed chunk may be reasoning-only; once visible content
            # or tool calls arrive, keep the same message and promote its display
            # type instead of persisting a separate reasoning message.
            existing_type = existing_message.normalized_message_type()
            new_type = new_message.normalized_message_type()
            if new_message.tool_calls:
                existing_message.type = MessageType.TOOL_CALL.value
                existing_message.message_type = MessageType.TOOL_CALL.value
            elif (
                existing_type == MessageType.REASONING_CONTENT.value
                and new_type
                not in {
                    MessageType.REASONING_CONTENT.value,
                    MessageType.EMPTY.value,
                }
            ):
                existing_message.type = new_type
                existing_message.message_type = new_type

            # 合并 tool_calls（流式 tool_calls 增量合并）
            if new_message.tool_calls is not None:
                if existing_message.tool_calls is None:
                    existing_message.tool_calls = []
                else:
                    existing_message.tool_calls = [
                        _tool_call_to_dict(tc) for tc in existing_message.tool_calls
                    ]

                # 遍历新的 tool_calls，优先按 index 合并，其次按 id 合并
                for new_tc in new_message.tool_calls:
                    new_tc = _tool_call_to_dict(new_tc)
                    tc_id = new_tc.get("id") or ""
                    tc_index = new_tc.get("index")
                    tc_function = (
                        new_tc.get("function", {})
                        if isinstance(new_tc.get("function", {}), dict)
                        else {}
                    )
                    tc_name = tc_function.get("name")
                    tc_args = tc_function.get("arguments")

                    # 查找是否已存在相同 id / index 的 tool_call
                    existing_tc = None
                    existing_tc_index = -1
                    if tc_id:
                        for idx, etc in enumerate(existing_message.tool_calls):
                            etc_id = (
                                etc.get("id")
                                if isinstance(etc, dict)
                                else getattr(etc, "id", None)
                            )
                            if etc_id == tc_id:
                                existing_tc = etc
                                existing_tc_index = idx
                                break
                    if existing_tc is None and tc_index is not None:
                        for idx, etc in enumerate(existing_message.tool_calls):
                            etc_index = (
                                etc.get("index")
                                if isinstance(etc, dict)
                                else getattr(etc, "index", None)
                            )
                            if etc_index == tc_index:
                                existing_tc = etc
                                existing_tc_index = idx
                                break
                    if (
                        existing_tc is None
                        and tc_index is None
                        and existing_message.tool_calls
                    ):
                        existing_tc = existing_message.tool_calls[-1]
                        existing_tc_index = len(existing_message.tool_calls) - 1

                    if existing_tc:
                        if not isinstance(existing_tc, dict):
                            existing_tc = _tool_call_to_dict(existing_tc)
                            existing_message.tool_calls[existing_tc_index] = existing_tc
                        if tc_id:
                            existing_tc["id"] = tc_id
                        if tc_index is not None and existing_tc.get("index") is None:
                            existing_tc["index"] = tc_index
                        if tc_name:
                            existing_tc.setdefault("function", {})
                            existing_tc["function"]["name"] = tc_name
                        if tc_args:
                            existing_tc.setdefault("function", {})
                            existing_args = (
                                existing_tc["function"].get("arguments") or ""
                            )
                            existing_tc["function"]["arguments"] = (
                                existing_args + tc_args
                            )
                    else:
                        # 添加新的 tool_call
                        existing_message.tool_calls.append(new_tc)
        else:
            old_messages.append(new_message)
            # logger.debug(f"MessageManager: 创建新消息 {new_message.message_id[:8]}... ")
        return old_messages

    @staticmethod
    def convert_messages_to_str(messages: List[MessageChunk]) -> str:
        """
        将消息列表转换为字符串格式

        Args:
            messages: 消息列表

        Returns:
            str: 格式化后的消息字符串
        """
        logger.info(f"AgentBase: 将 {len(messages)} 条消息转换为字符串")

        messages = MessageManager.strip_turn_status_from_llm_context(list(messages))

        messages_str_list = []

        for msg in messages:
            if msg is None:
                continue
            # 提取文本内容（处理多模态格式）
            content_str = MessageManager._extract_text_from_content(msg.content)
            if msg.role == "user":
                messages_str_list.append(f"User: {content_str}")
            elif msg.role == "assistant":
                if content_str:
                    messages_str_list.append(f"AI: {content_str}")
                elif msg.tool_calls is not None:
                    messages_str_list.append(f"AI: Tool calls: {msg.tool_calls}")
            elif msg.role == "tool":
                messages_str_list.append(f"Tool: {content_str}")

        result = "\n".join(messages_str_list) or "None"
        logger.info(
            f"AgentBase: 转换后字符串长度: {MessageManager._calculate_str_token_length_static(result)}"
        )
        return result

    @staticmethod
    def _is_compress_history_tool_call(msg: MessageChunk) -> bool:
        """
        判断消息是否为调用 compress_conversation_history 工具的 Assistant 消息

        Args:
            msg: 消息对象

        Returns:
            bool: 是否为调用压缩历史工具的消息
        """
        # 只检查 Assistant 角色的消息
        if msg.role != MessageRole.ASSISTANT.value:
            return False

        # 检查 tool_calls 字段
        if msg.tool_calls is None:
            return False

        for tool_call in msg.tool_calls:
            # 获取工具名称
            if hasattr(tool_call, "function"):
                tool_name = getattr(tool_call.function, "name", None)  # pyright: ignore[reportAttributeAccessIssue]
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get("function", {}).get("name")
            else:
                tool_name = None

            if tool_name == COMPRESS_HISTORY_TOOL_NAME:
                return True

        return False

    @staticmethod
    def _compress_tool_call_ids(msg: MessageChunk) -> List[str]:
        if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
            return []
        ids: List[str] = []
        for tool_call in msg.tool_calls:
            name, tid = MessageManager._tool_call_entry_name_and_id(tool_call)
            if name == COMPRESS_HISTORY_TOOL_NAME and tid:
                ids.append(tid)
        return ids

    @staticmethod
    def _is_successful_compression_result(msg: MessageChunk) -> bool:
        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        return (
            msg.role == MessageRole.TOOL.value
            and metadata.get("tool_name") == COMPRESS_HISTORY_TOOL_NAME
            and metadata.get("status") == "success"
            and metadata.get("compression_anchor") is True
        )

    @staticmethod
    def _compression_pairs(
        messages: List[MessageChunk],
    ) -> List[Dict[str, Any]]:
        """Return valid compression pairs with source coverage metadata."""
        id_to_index = {
            msg.message_id: idx
            for idx, msg in enumerate(messages)
            if msg.message_id is not None
        }
        pairs: List[Dict[str, Any]] = []
        for assistant_idx, assistant_msg in enumerate(messages):
            tool_call_ids = MessageManager._compress_tool_call_ids(assistant_msg)
            if not tool_call_ids:
                continue
            result_indices: List[int] = []
            for idx in range(assistant_idx + 1, len(messages)):
                msg = messages[idx]
                if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                    break
                if (
                    msg.role == MessageRole.TOOL.value
                    and msg.tool_call_id in tool_call_ids
                    and MessageManager._is_successful_compression_result(msg)
                ):
                    result_indices.append(idx)
                    break
            if not result_indices:
                continue
            result_msg = messages[result_indices[0]]
            metadata = (
                result_msg.metadata if isinstance(result_msg.metadata, dict) else {}
            )
            raw_summary = result_msg.get_content()
            payload = MessageManager._safe_parse_compression_payload(raw_summary)
            summary = payload.get("summary") if isinstance(payload, dict) else None
            if (
                (not isinstance(summary, str) or not summary.strip())
                and isinstance(raw_summary, str)
                and not raw_summary.lstrip().startswith("{")
            ):
                # Historical sessions may have persisted the successful summary
                # as plain text before the structured payload was introduced.
                summary = raw_summary
            if not isinstance(summary, str) or not summary.strip():
                continue
            source_ids = [
                mid
                for mid in metadata.get("source_message_ids", [])
                if isinstance(mid, str)
            ]
            covered_indices = {
                id_to_index[mid] for mid in source_ids if mid in id_to_index
            }
            if source_ids and 0 < len(covered_indices) < len(set(source_ids)):
                # A partially resolved range could hide only part of the source
                # while presenting the summary as complete. Treat it as an
                # invalid audit record instead.
                continue
            start_id = metadata.get("source_start_message_id")
            end_id = metadata.get("source_end_message_id")
            if (
                not covered_indices
                and start_id in id_to_index
                and end_id in id_to_index
            ):
                start_idx = id_to_index[start_id]
                end_idx = id_to_index[end_id]
                if start_idx <= end_idx:
                    covered_indices.update(range(start_idx, end_idx + 1))
            if not covered_indices:
                # A provider-overflow retry works from the already-collapsed
                # inference view, so the source messages referenced by a valid
                # summary may no longer be present. Keep that detached summary
                # as a first-class node so a later hierarchical summary can
                # include it. Metadata without a real summary remains invalid.
                has_declared_source = bool(source_ids) or (
                    isinstance(start_id, str)
                    and bool(start_id)
                    and isinstance(end_id, str)
                    and bool(end_id)
                )
                if (
                    not has_declared_source
                    or not summary.strip()
                ):
                    continue
            pair_indices = {assistant_idx, *result_indices}
            pairs.append(
                {
                    "assistant_idx": assistant_idx,
                    "result_indices": result_indices,
                    "pair_indices": pair_indices,
                    "covered_indices": covered_indices,
                    "detached_coverage": not bool(covered_indices),
                    "insert_idx": max(pair_indices),
                }
            )
        return pairs

    @staticmethod
    def _expanded_compression_pairs(
        messages: List[MessageChunk],
    ) -> List[Dict[str, Any]]:
        pairs = MessageManager._compression_pairs(messages)
        if not pairs:
            return []
        changed = True
        while changed:
            changed = False
            for pair in pairs:
                expanded = set(pair["covered_indices"])
                for other in pairs:
                    if other is pair:
                        continue
                    if expanded.intersection(other["pair_indices"]):
                        expanded.update(other["covered_indices"])
                        expanded.update(other["pair_indices"])
                if expanded != pair["covered_indices"]:
                    pair["covered_indices"] = expanded
                    changed = True
        for pair in pairs:
            pair["covered_by_later"] = any(
                other["assistant_idx"] > pair["assistant_idx"]
                and pair["pair_indices"].issubset(other["covered_indices"])
                for other in pairs
                if other is not pair
            )
        return pairs

    @staticmethod
    def _safe_parse_compression_payload(content: Any) -> Dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            return {}
        try:
            payload = json.loads(content)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def build_compact_manifest(messages: List[MessageChunk]) -> Dict[str, Any]:
        """Build a derived index for compression anchors and their coverage.

        The manifest is for audit/debugging only. Inference still recomputes the
        coverage graph directly from messages.
        """
        pairs = MessageManager._expanded_compression_pairs(messages)
        message_id_by_index = {
            idx: msg.message_id
            for idx, msg in enumerate(messages)
            if msg.message_id is not None
        }
        pair_entries: List[Dict[str, Any]] = []
        covered_message_ids: set[str] = set()
        visible_result_ids: List[str] = []

        for pair in pairs:
            result_indices = pair.get("result_indices", [])
            result_idx = result_indices[0] if result_indices else None
            result_msg = (
                messages[result_idx]
                if isinstance(result_idx, int) and 0 <= result_idx < len(messages)
                else None
            )
            assistant_idx = pair.get("assistant_idx")
            assistant_msg = (
                messages[assistant_idx]
                if isinstance(assistant_idx, int) and 0 <= assistant_idx < len(messages)
                else None
            )
            metadata = (
                result_msg.metadata
                if result_msg and isinstance(result_msg.metadata, dict)
                else {}
            )
            payload = MessageManager._safe_parse_compression_payload(
                result_msg.get_content() if result_msg else None
            )
            stats = (
                payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
            )
            summary = (
                payload.get("summary")
                if isinstance(payload.get("summary"), str)
                else ""
            )
            pair_message_ids = [
                message_id_by_index[idx]
                for idx in sorted(pair.get("pair_indices", set()))
                if idx in message_id_by_index
            ]
            pair_covered_ids = [
                message_id_by_index[idx]
                for idx in sorted(pair.get("covered_indices", set()))
                if idx in message_id_by_index
            ]
            covered_message_ids.update(pair_covered_ids)
            is_visible = not pair.get("covered_by_later")
            if is_visible and result_msg and result_msg.message_id:
                visible_result_ids.append(result_msg.message_id)
            entry = {
                "assistant_message_id": assistant_msg.message_id
                if assistant_msg
                else None,
                "assistant_index": assistant_idx,
                "result_message_ids": [
                    message_id_by_index[idx]
                    for idx in result_indices
                    if idx in message_id_by_index
                ],
                "pair_message_ids": pair_message_ids,
                "source_start_message_id": metadata.get("source_start_message_id"),
                "source_end_message_id": metadata.get("source_end_message_id"),
                "source_message_ids": metadata.get("source_message_ids", []),
                "source_message_count": metadata.get("source_message_count"),
                "covered_message_ids": pair_covered_ids,
                "covered_message_count": len(pair_covered_ids),
                "covered_by_later": bool(pair.get("covered_by_later")),
                "visible": is_visible,
                "insert_index": pair.get("insert_idx"),
                "status": metadata.get("status"),
                "stats": {
                    key: stats[key]
                    for key in (
                        "original_tokens",
                        "compressed_tokens",
                        "compression_ratio",
                        "token_estimate_kind",
                        "source_characters",
                        "summary_characters",
                        "source_message_count",
                        "compression_input_message_count",
                        "summary_parse_status",
                        "compression_batch_count",
                    )
                    if key in stats
                },
                "summary_preview": summary[:240],
            }
            pair_entries.append(entry)

        ordered_covered_ids = [
            msg.message_id for msg in messages if msg.message_id in covered_message_ids
        ]
        return {
            "version": 1,
            "generated_at": datetime.datetime.now().isoformat(),
            "total_messages": len(messages),
            "compression_pair_count": len(pair_entries),
            "visible_pair_count": sum(1 for pair in pair_entries if pair["visible"]),
            "covered_message_count": len(ordered_covered_ids),
            "covered_message_ids": ordered_covered_ids,
            "visible_compression_result_message_ids": visible_result_ids,
            "pairs": pair_entries,
        }

    @staticmethod
    def _tool_result_ids_for_assistant(msg: MessageChunk) -> set[str]:
        ids: set[str] = set()
        if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
            return ids
        for tool_call in msg.tool_calls:
            _, tid = MessageManager._tool_call_entry_name_and_id(tool_call)
            if tid:
                ids.add(tid)
        return ids

    @staticmethod
    def _pair_safe_protected_indices(
        messages: List[MessageChunk], recent_count: int
    ) -> set[int]:
        if recent_count <= 0 or not messages:
            return set()
        start = max(0, len(messages) - recent_count)
        protected = set(range(start, len(messages)))
        changed = True
        while changed:
            changed = False
            protected_ids: set[str] = set()
            for idx in list(protected):
                msg = messages[idx]
                if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                    protected_ids.update(
                        MessageManager._tool_result_ids_for_assistant(msg)
                    )
                elif msg.role == MessageRole.TOOL.value and msg.tool_call_id:
                    for prev_idx in range(idx - 1, -1, -1):
                        prev_msg = messages[prev_idx]
                        if (
                            prev_msg.role == MessageRole.ASSISTANT.value
                            and msg.tool_call_id
                            in MessageManager._tool_result_ids_for_assistant(prev_msg)
                        ):
                            if prev_idx not in protected:
                                protected.add(prev_idx)
                                changed = True
                            break
            for idx, msg in enumerate(messages):
                if (
                    msg.role == MessageRole.TOOL.value
                    and msg.tool_call_id in protected_ids
                    and idx not in protected
                ):
                    protected.add(idx)
                    changed = True
        return protected

    @staticmethod
    def _last_tool_call_result_index(
        messages: List[MessageChunk],
        tool_name: str,
    ) -> Optional[int]:
        """Return the matching tool-result index for the last assistant tool call."""
        last_tool_call_id: Optional[str] = None
        for msg in messages:
            if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                name, tid = MessageManager._tool_call_entry_name_and_id(tc)
                if name == tool_name and tid:
                    last_tool_call_id = tid
        if not last_tool_call_id:
            return None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if (
                msg.role == MessageRole.TOOL.value
                and msg.tool_call_id == last_tool_call_id
            ):
                return idx
        return None

    @staticmethod
    def _base_inference_view(messages: List[MessageChunk]) -> List[MessageChunk]:
        if not messages:
            return []
        messages = MessageManager.strip_rejected_tool_calls_from_llm_context(messages)
        messages = MessageManager.strip_historical_search_memory_from_llm_context(
            messages
        )
        filtered_messages = [
            msg
            for msg in messages
            if MessageManager.should_include_in_llm(msg)
        ]
        filtered_messages = MessageManager._coalesce_reasoning_for_inference(
            filtered_messages
        )
        pairs = MessageManager._expanded_compression_pairs(filtered_messages)
        covered_by_visible: set[int] = set()
        hidden_pairs: set[int] = set()
        for pair in pairs:
            if pair.get("covered_by_later"):
                hidden_pairs.update(pair["pair_indices"])
                continue
            covered_by_visible.update(pair["covered_indices"])
        out: List[MessageChunk] = []
        for idx, msg in enumerate(filtered_messages):
            if msg.role == MessageRole.SYSTEM.value:
                # Keep legacy system IDs available while validating compression
                # coverage, then enforce the normal provider-view exclusion.
                continue
            if idx in hidden_pairs:
                continue
            if idx in covered_by_visible:
                if any(
                    idx in pair["pair_indices"] and not pair.get("covered_by_later")
                    for pair in pairs
                ):
                    out.append(msg)
                continue
            out.append(msg)
        return MessageManager.strip_turn_status_from_llm_context(out)

    @staticmethod
    def _coalesce_reasoning_for_inference(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """Attach reasoning to the matching assistant response.

        Current durable messages keep reasoning beside content/tool_calls;
        legacy sessions may still contain a dedicated reasoning display chunk.
        Keep the complete response in this provider-neutral view; provider-specific
        request preparation decides whether ``reasoning_content`` is supported.
        """
        output: List[MessageChunk] = []
        pending_reasoning: List[str] = []
        pending_assistant_messages: List[MessageChunk] = []
        pending_response_id: Optional[str] = None
        pending_agent_name: Optional[str] = None
        message_id_counts: Dict[str, int] = {}
        for message in messages:
            if message.role != MessageRole.ASSISTANT.value or not message.message_id:
                continue
            message_id_counts[message.message_id] = (
                message_id_counts.get(message.message_id, 0) + 1
            )

        def response_id(message: MessageChunk) -> Optional[str]:
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            value = metadata.get("llm_response_id")
            if value:
                return str(value)
            if message.message_id and message_id_counts.get(message.message_id, 0) > 1:
                return str(message.message_id)
            return None

        def belongs_to_pending_response(message: MessageChunk) -> bool:
            if (
                pending_agent_name
                and message.agent_name
                and pending_agent_name != message.agent_name
            ):
                return False
            current_response_id = response_id(message)
            if pending_response_id is None and current_response_id is None:
                # Legacy sessions have no response identity; retain adjacency
                # fallback only when both sides are legacy messages.
                return True
            return pending_response_id == current_response_id

        def flush_pending_assistant_messages() -> None:
            nonlocal pending_agent_name, pending_response_id
            if pending_reasoning and pending_assistant_messages:
                primary = pending_assistant_messages[0]
                contents = [item.content for item in pending_assistant_messages]
                if all(
                    content is None or isinstance(content, str) for content in contents
                ):
                    primary.content = "".join(
                        content for content in contents if isinstance(content, str)
                    )
                    primary.reasoning_content = "".join(pending_reasoning) + "".join(
                        item.reasoning_content or ""
                        for item in pending_assistant_messages
                    )
                    output.append(primary)
                else:
                    primary.reasoning_content = "".join(pending_reasoning) + (
                        primary.reasoning_content or ""
                    )
                    output.extend(pending_assistant_messages)
            else:
                output.extend(pending_assistant_messages)
            pending_assistant_messages.clear()
            pending_reasoning.clear()
            pending_response_id = None
            pending_agent_name = None

        def pending_visible_content() -> str:
            return "".join(
                content
                for item in pending_assistant_messages
                if isinstance((content := item.get_content()), str)
            )

        for source in messages:
            message = deepcopy(source)
            is_reasoning_message = message.matches_message_types(
                [MessageType.REASONING_CONTENT.value]
            )
            if is_reasoning_message:
                if (
                    pending_reasoning or pending_assistant_messages
                ) and not belongs_to_pending_response(message):
                    flush_pending_assistant_messages()
                reasoning = message.reasoning_content or message.get_content()
                if isinstance(reasoning, str) and reasoning:
                    pending_response_id = response_id(message)
                    pending_agent_name = message.agent_name
                    pending_reasoning.append(reasoning)
                continue

            if message.role == MessageRole.ASSISTANT.value:
                if (
                    pending_reasoning or pending_assistant_messages
                ) and not belongs_to_pending_response(message):
                    flush_pending_assistant_messages()
                if pending_reasoning and not message.tool_calls:
                    if pending_agent_name is None and message.agent_name:
                        pending_agent_name = message.agent_name
                    pending_assistant_messages.append(message)
                    continue
                if message.tool_calls:
                    buffered_reasoning = "".join(
                        item.reasoning_content or ""
                        for item in pending_assistant_messages
                    )
                    buffered_content = pending_visible_content()
                    if buffered_content:
                        current_content = (
                            message.content if isinstance(message.content, str) else ""
                        )
                        message.content = buffered_content + current_content
                    pending_assistant_messages.clear()
                    combined = "".join(pending_reasoning) + buffered_reasoning
                    if message.reasoning_content:
                        combined += message.reasoning_content
                    message.reasoning_content = combined or None
                pending_reasoning = []
                pending_response_id = None
                pending_agent_name = None
            elif pending_reasoning or pending_assistant_messages:
                flush_pending_assistant_messages()

            output.append(message)

        flush_pending_assistant_messages()
        return output

    @staticmethod
    def strip_rejected_tool_calls_from_llm_context(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """Remove rejected provisional tool-call pairs from provider history.

        Low-latency streaming keeps these messages in the durable ledger so the UI
        can close its provisional tool card, but an unavailable/invalid call must
        not be replayed to the model. A tool result cannot be sent by itself, so
        both the rejected result and its matching assistant tool_call are removed.
        """

        rejected_ids = {
            str(msg.tool_call_id)
            for msg in messages
            if msg.role == MessageRole.TOOL.value
            and msg.tool_call_id
            and isinstance(msg.metadata, dict)
            and msg.metadata.get("streamed_tool_rejected") is True
        }
        if not rejected_ids:
            return list(messages)

        filtered: List[MessageChunk] = []
        for msg in messages:
            if (
                msg.role == MessageRole.TOOL.value
                and msg.tool_call_id
                and str(msg.tool_call_id) in rejected_ids
            ):
                continue
            if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                kept_tool_calls = [
                    tool_call
                    for tool_call in msg.tool_calls
                    if str(MessageManager._tool_call_entry_name_and_id(tool_call)[1])
                    not in rejected_ids
                ]
                if not kept_tool_calls:
                    if MessageManager._message_has_non_empty_content(msg):
                        filtered.append(replace(msg, tool_calls=None))
                    continue
                if len(kept_tool_calls) != len(msg.tool_calls):
                    filtered.append(replace(msg, tool_calls=kept_tool_calls))
                    continue
            filtered.append(msg)
        return filtered

    @staticmethod
    def should_include_in_llm(msg: MessageChunk) -> bool:
        """Return whether a ledger message belongs in a new LLM request.

        ``next_request`` runtime diagnostics remain durable audit records, but are
        removed from inference after the first logical request consumes them.
        Legacy hidden diagnostics predate ``llm_scope`` and have already been
        consumed by definition, so they are excluded from future requests.
        """

        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        scope = metadata.get("llm_scope")
        if scope == "never":
            return False
        if scope == "next_request":
            return metadata.get("llm_state", "pending") == "pending"
        if scope in {None, "durable"}:
            if scope is None and (
                metadata.get("runtime_notice") == "unavailable_tool_rejected"
                or metadata.get("runtime_diagnostic_source")
                == "tool_call_argument_parse"
            ):
                return False
            return True
        return True

    @staticmethod
    def pending_next_request_message_ids(
        messages: Sequence[Union[MessageChunk, Dict[str, Any]]],
    ) -> List[str]:
        message_ids: List[str] = []
        for raw_message in messages:
            message = (
                MessageChunk.from_dict(raw_message)
                if isinstance(raw_message, dict)
                else raw_message
            )
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if (
                metadata.get("llm_scope") == "next_request"
                and metadata.get("llm_state", "pending") == "pending"
                and message.message_id
            ):
                message_ids.append(message.message_id)
        return message_ids

    @staticmethod
    def filter_messages_for_llm_scope(
        messages: Sequence[Union[MessageChunk, Dict[str, Any]]],
    ) -> List[Union[MessageChunk, Dict[str, Any]]]:
        filtered: List[Union[MessageChunk, Dict[str, Any]]] = []
        for raw_message in messages:
            message = (
                MessageChunk.from_dict(raw_message)
                if isinstance(raw_message, dict)
                else raw_message
            )
            if MessageManager.should_include_in_llm(message):
                filtered.append(raw_message)
        return filtered

    @staticmethod
    def build_inference_view(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """Build the provider-facing history view from durable messages.

        Main-session history is reduced only by successful persistent LLM
        summaries. Legacy artifact-reference messages remain readable as ordinary
        historical text, but this path never creates or truncates content.
        """
        return MessageManager._base_inference_view(messages)

    def insert_messages_after(
        self, message_id: str, messages: Union[MessageChunk, List[MessageChunk]]
    ) -> bool:
        if isinstance(messages, MessageChunk):
            messages = [messages]
        incoming_ids = {
            message.message_id for message in messages if message.message_id is not None
        }
        if incoming_ids:
            self.messages = [
                message
                for message in self.messages
                if message.message_id not in incoming_ids
            ]
        insert_at = None
        for idx, message in enumerate(self.messages):
            if message.message_id == message_id:
                insert_at = idx + 1
                break
        if insert_at is None:
            logger.warning(
                "MessageManager: 未找到 compression 插入锚点 message_id=%s，跳过写入，避免追加到会话末尾",
                message_id,
            )
            return False
        for offset, message in enumerate(messages):
            if message.role == MessageRole.SYSTEM.value:
                self.stats["system_messages_rejected"] += 1
                continue
            self.messages.insert(insert_at + offset, message)
        self.stats["total_messages"] = len(self.messages)
        self.stats["total_chunks"] += len(messages)
        self.stats["last_updated"] = datetime.datetime.now().isoformat()
        self._refresh_history_anchor_index()
        return True

    @staticmethod
    def select_llm_compression_segment(
        messages: List[MessageChunk],
        active_protection_count: int = DEFAULT_LLM_PROTECTION_COUNT,
    ) -> Optional[List[MessageChunk]]:
        """Select history for one persistent LLM summary.

        The latest user message and a pair-safe recent tail are always protected.
        With multiple visible turns, every unprotected message before the latest
        user belongs to history. With a single visible turn, only the closed
        assistant/tool prefix is eligible. The latest visible summary pair is
        included so every new summary supersedes the previous one.
        """
        effective = MessageManager._base_inference_view(messages)
        if not effective:
            return None
        protected = MessageManager._pair_safe_protected_indices(
            effective, active_protection_count
        )
        user_indices = [
            idx for idx, msg in enumerate(effective) if msg.role == MessageRole.USER.value
        ]
        last_user_idx = user_indices[-1] if user_indices else None
        selected: set[int] = set()

        visible_pairs = [
            pair
            for pair in MessageManager._expanded_compression_pairs(effective)
            if not pair.get("covered_by_later")
        ]
        if visible_pairs:
            latest_pair = max(visible_pairs, key=lambda pair: pair["assistant_idx"])
            pair_indices = set(latest_pair["pair_indices"])
            # Summary nodes are historical memory rather than active-turn
            # messages. They must remain eligible even when the pair happens to
            # fall inside the numeric recent-message tail; otherwise a second
            # provider overflow cannot build the next hierarchical summary.
            selected.update(pair_indices)

        if last_user_idx is not None and len(user_indices) > 1:
            selected.update(
                idx
                for idx in range(last_user_idx)
                if idx not in protected
                and effective[idx].role != MessageRole.SYSTEM.value
            )
        elif last_user_idx is not None:
            protected_after_user = [idx for idx in protected if idx > last_user_idx]
            active_limit = (
                min(protected_after_user) if protected_after_user else len(effective)
            )
            safe_end: Optional[int] = None
            for idx in range(last_user_idx + 1, active_limit):
                msg = effective[idx]
                if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                    continue
                result_ids = MessageManager._tool_result_ids_for_assistant(msg)
                if not result_ids:
                    continue
                matched_result_indices = {
                    result_idx
                    for result_idx in range(idx + 1, active_limit)
                    if effective[result_idx].role == MessageRole.TOOL.value
                    and effective[result_idx].tool_call_id in result_ids
                }
                matched_ids = {
                    effective[result_idx].tool_call_id
                    for result_idx in matched_result_indices
                }
                if result_ids.issubset(matched_ids):
                    safe_end = max(matched_result_indices)
            if safe_end is not None:
                selected.update(
                    idx
                    for idx in range(last_user_idx + 1, safe_end + 1)
                    if idx not in protected
                )
        elif effective:
            selected.update(
                idx for idx in range(len(effective)) if idx not in protected
            )

        # A provider tool pair is atomic. Drop incomplete pairs rather than
        # hiding only one side behind a summary anchor.
        for idx, msg in enumerate(effective):
            if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                continue
            result_ids = MessageManager._tool_result_ids_for_assistant(msg)
            result_indices = {
                result_idx
                for result_idx, result in enumerate(effective)
                if result.role == MessageRole.TOOL.value
                and result.tool_call_id in result_ids
            }
            if idx in selected and (
                not result_ids
                or not result_ids.issubset(
                    {effective[result_idx].tool_call_id for result_idx in result_indices}
                )
                or not result_indices.issubset(selected)
            ):
                selected.discard(idx)
                selected.difference_update(result_indices)
            elif idx not in selected:
                selected.difference_update(result_indices)

        if last_user_idx is not None:
            selected.discard(last_user_idx)
        segment = [effective[idx] for idx in sorted(selected)]
        if not any(
            msg.role in {MessageRole.ASSISTANT.value, MessageRole.TOOL.value}
            for msg in segment
        ):
            return None
        return segment

    @staticmethod
    def _tool_call_entry_name_and_id(tc: Any) -> Tuple[Optional[str], Optional[str]]:
        """从流式或序列化后的 tool_call 条目中解析工具名与 id。"""
        tid: Optional[str] = None
        name: Optional[str] = None
        if isinstance(tc, dict):
            tid = tc.get("id")
            fn = tc.get("function")
            if isinstance(fn, dict):
                name = fn.get("name")
        else:
            tid = getattr(tc, "id", None)
            fn = getattr(tc, "function", None)
            if fn is not None:
                name = getattr(fn, "name", None)
        return name, tid

    @staticmethod
    def _message_has_non_empty_content(
        msg: Union[MessageChunk, Dict[str, Any]],
    ) -> bool:
        """判断 assistant/user 等是否含有可视为「有效正文」的内容（含多模态文本段）。"""
        content = msg.get("content") if isinstance(msg, dict) else msg.content
        if content is None:
            return False
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    t = part.get("text") or part.get("content")
                    if isinstance(t, str) and t.strip():
                        return True
            return False
        return bool(content)

    @staticmethod
    def strip_historical_search_memory_from_llm_context(
        messages: List[MessageItemT],
    ) -> List[MessageItemT]:
        """Remove completed-turn ``search_memory`` pairs from LLM context.

        ``search_memory`` calls remain in the durable ledger for history, UI,
        and audit purposes. Once a newer user message starts another turn, the
        older search call and its matching tool result no longer need to be
        replayed to the model. Calls after the latest user message remain
        available so the current turn can consume fresh retrieval results.

        Mixed assistant tool-call messages are pruned pair-safely: unrelated
        calls and assistant text are retained, and an assistant message is
        dropped only when removing the historical search leaves it empty.
        """
        if not messages:
            return []

        def message_role(msg: MessageItemT) -> Optional[str]:
            role = msg.get("role") if isinstance(msg, dict) else msg.role
            return role.value if isinstance(role, MessageRole) else role

        def message_tool_calls(msg: MessageItemT) -> List[Any]:
            tool_calls = (
                msg.get("tool_calls") if isinstance(msg, dict) else msg.tool_calls
            )
            return list(tool_calls or [])

        def message_tool_call_id(msg: MessageItemT) -> Optional[str]:
            tool_call_id = (
                msg.get("tool_call_id") if isinstance(msg, dict) else msg.tool_call_id
            )
            return str(tool_call_id) if tool_call_id else None

        def is_real_user_boundary(msg: MessageItemT) -> bool:
            if message_role(msg) != MessageRole.USER.value:
                return False
            metadata = msg.get("metadata") if isinstance(msg, dict) else msg.metadata
            metadata = metadata if isinstance(metadata, dict) else {}
            return metadata.get("runtime_continuation_guidance") is not True

        def with_tool_calls(
            msg: MessageItemT, kept_tool_calls: List[Any]
        ) -> MessageItemT:
            if isinstance(msg, dict):
                copied = deepcopy(msg)
                if kept_tool_calls:
                    copied["tool_calls"] = kept_tool_calls
                else:
                    copied.pop("tool_calls", None)
                return copied  # pyright: ignore[reportReturnType]
            return replace(msg, tool_calls=kept_tool_calls or None)  # pyright: ignore[reportReturnType]

        latest_user_idx: Optional[int] = None
        for idx in range(len(messages) - 1, -1, -1):
            if is_real_user_boundary(messages[idx]):
                latest_user_idx = idx
                break
        if latest_user_idx is None:
            return list(messages)

        historical_search_ids: set[str] = set()
        for msg in messages[:latest_user_idx]:
            tool_calls = message_tool_calls(msg)
            if message_role(msg) != MessageRole.ASSISTANT.value or not tool_calls:
                continue
            for tool_call in tool_calls:
                name, tool_call_id = MessageManager._tool_call_entry_name_and_id(
                    tool_call
                )
                if name == SEARCH_MEMORY_TOOL_NAME and tool_call_id:
                    historical_search_ids.add(str(tool_call_id))

        out: List[MessageItemT] = []
        for idx, msg in enumerate(messages):
            tool_call_id = message_tool_call_id(msg)
            if (
                message_role(msg) == MessageRole.TOOL.value
                and tool_call_id
                and tool_call_id in historical_search_ids
            ):
                continue

            tool_calls = message_tool_calls(msg)
            if (
                idx < latest_user_idx
                and message_role(msg) == MessageRole.ASSISTANT.value
                and tool_calls
            ):
                kept_tool_calls = [
                    tool_call
                    for tool_call in tool_calls
                    if MessageManager._tool_call_entry_name_and_id(tool_call)[0]
                    != SEARCH_MEMORY_TOOL_NAME
                ]
                if len(kept_tool_calls) == len(tool_calls):
                    out.append(msg)
                elif kept_tool_calls:
                    out.append(with_tool_calls(msg, kept_tool_calls))
                elif MessageManager._message_has_non_empty_content(msg):
                    out.append(with_tool_calls(msg, []))
                continue

            out.append(msg)

        return out

    @staticmethod
    def strip_turn_status_from_llm_context(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """
        从即将发往 LLM 的消息列表中移除 turn_status 工具调用及其 tool 回复。

        例外：被 SimpleAgent 标记 ``metadata.turn_status_rejected=True`` 或
        ``metadata.coerced_from`` 的 tool 结果必须保留（连同对应 assistant tool_call），
        让模型下一轮能看到"先写总结再调 turn_status"的反馈或"上次调 X 被改写"的事实，
        避免反复重蹈覆辙；SSE 侧仍由 ``_redact_hidden_tools_from_chunk`` 按
        tool_call_id 隐藏，前端不会感知。

        不影响 message_manager.messages / messages.json 中的原始记录；
        仅在构造 API 请求或 extract_messages_for_inference 出口处使用。
        """
        if not messages:
            return []

        turn_ids: set[str] = set()
        last_turn_id: Optional[str] = None
        for msg in messages:
            if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                name, tid = MessageManager._tool_call_entry_name_and_id(tc)
                if name == TURN_STATUS_TOOL_NAME and tid:
                    turn_ids.add(tid)
                    last_turn_id = tid

        preserved_ids: set[str] = set()
        for msg in messages:
            if (
                msg.role == MessageRole.TOOL.value
                and msg.tool_call_id
                and msg.tool_call_id in turn_ids
                and isinstance(msg.metadata, dict)
                and (
                    msg.metadata.get("turn_status_rejected") is True
                    or msg.metadata.get("coerced_from")
                )
            ):
                preserved_ids.add(msg.tool_call_id)

        # 保留最后一条 turn_status pair（无论 status 类型），让 LLM 看到自己上一轮的状态决策，
        # 避免反复刷 turn_status；历史 turn_status 仍按现策略剔除。
        if last_turn_id is not None:
            preserved_ids.add(last_turn_id)

        strip_ids = turn_ids - preserved_ids

        out: List[MessageChunk] = []
        for msg in messages:
            if (
                msg.role == MessageRole.TOOL.value
                and msg.tool_call_id
                and msg.tool_call_id in strip_ids
            ):
                continue

            if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                kept: List[Any] = []
                for tc in msg.tool_calls:
                    name, tid = MessageManager._tool_call_entry_name_and_id(tc)
                    # 仅当这条 turn_status 调用对应的 tool 结果未被标记 rejected/coerced 时才剔除；
                    # 被保留的 pair 整体保留，避免出现孤儿 tool 消息。
                    if name == TURN_STATUS_TOOL_NAME and tid in strip_ids:
                        continue
                    kept.append(tc)

                if not kept:
                    if MessageManager._message_has_non_empty_content(msg):
                        out.append(replace(msg, tool_calls=None))
                    # 既无正文又仅含 turn_status：整段 assist 消息不进入 LLM
                    continue

                if len(kept) == len(msg.tool_calls):
                    out.append(msg)
                else:
                    out.append(replace(msg, tool_calls=kept))
                continue

            out.append(msg)

        return out

    @staticmethod
    def extract_messages_for_inference(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """
        从消息列表中提取用于推理的消息
        类似 extract_all_context_messages，但用于任意输入的消息列表（而非 self.messages）

        策略：
        1. 过滤掉 REASONING_CONTENT 类型的消息
        2. 检测成功的 compress_conversation_history anchor pair
        3. 按 source coverage 隐藏已被成功 summary 覆盖的旧消息
        4. 保留未被更高层 summary 覆盖的 compression pair 作为摘要节点

        Args:
            messages: 原始消息列表

        Returns:
            List[MessageChunk]: 提取后的消息列表
        """
        return MessageManager.build_inference_view(messages)

    def extract_all_context_messages(
        self,
        recent_turns: int = 0,
        last_turn_user_only: bool = True,
        allowed_message_types: Optional[List[str]] = None,
    ) -> List[MessageChunk]:
        """
        提取所有有意义的上下文消息，包括用户消息和助手消息，最后一个消息对话，可选是否只提取用户消息，如果只提取用户消息，即是本次请求的上下文，否则带上本次执行已有内容

        注意：本方法不再按 active_start_index 做硬截断。
        发往 LLM 的最终长度控制由统一 context builder 处理；这里会先解析
        compress_conversation_history 覆盖图，隐藏已被成功压缩锚点覆盖的旧消息。
        本方法仍会按 recent_turns 限制对话轮数（辅助 Agent 依赖此行为）。

        Args:
            recent_turns: 最近的对话轮数，0表示不限制
            last_turn_user_only: 是否只提取最后一个对话轮的用户消息，默认是True
            allowed_message_types: 允许保留的消息类型列表，默认为 None (使用内置默认列表)

        Returns:
            提取后的消息列表
        """
        all_context_messages = []
        chat_list = []

        # 默认允许的消息类型
        if allowed_message_types is None:
            allowed_message_types = [
                MessageType.ASSISTANT_TEXT.value,
                MessageType.FINAL_ANSWER.value,
                MessageType.DO_SUBTASK_RESULT.value,
                MessageType.TOOL_CALL.value,
                MessageType.TASK_ANALYSIS.value,
                MessageType.REASONING_CONTENT.value,
                MessageType.TOOL_CALL_RESULT.value,
                MessageType.SKILL_OBSERVATION.value,
                MessageType.AGENT_EXECUTION_ERROR.value,
                MessageType.SYSTEM_TRIGGERED_RUN.value,
            ]

        # 全量消息进入；压缩覆盖关系由 build_inference_view 统一处理。
        active_messages = MessageManager.build_inference_view(self.messages)

        for msg in active_messages:
            if msg.is_user_input_message():
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                if len(chat_list) > 0:
                    chat_list[-1].append(msg)
                else:
                    chat_list.append([msg])
        if recent_turns > 0:
            chat_list = chat_list[-recent_turns:]

        # 最后一个对话，只提取用户消息
        if last_turn_user_only and len(chat_list) > 0:
            last_chat = chat_list[-1]
            all_context_messages.append(last_chat[0])
            chat_list = chat_list[:-1]
        # 合并消息（长度限制由上层 _prepare_messages_for_llm 统一控制）
        for chat in chat_list[::-1]:
            merged_messages = []
            merged_messages.append(chat[0])

            for msg in chat[1:]:
                if msg.matches_message_types(allowed_message_types):
                    merged_messages.append(msg)

            all_context_messages.extend(merged_messages[::-1])

        result_messages = all_context_messages[::-1]
        # 打印提取结果的统计信息
        total_tokens = MessageManager.calculate_messages_token_length(result_messages)
        logger.debug(
            f"MessageManager: 提取所有上下文消息完成，最近轮数：{recent_turns}，是否只提取最后一个对话轮的用户消息：{last_turn_user_only}，消息数量：{len(result_messages)}，总token长度：{total_tokens}"
        )
        return result_messages

    @staticmethod
    def _group_messages_indices(messages: List[MessageChunk]) -> List[List[int]]:
        """
        将消息索引分组
        规则：User 消息标志着新组的开始
        Group Structure:
        - Group 0 (Maybe System/Orphan): [0, ..., k]
        - Group 1 (User+): [u1, ..., u2-1]
        """
        groups = []
        if not messages:
            return []

        current_group = []
        for i, msg in enumerate(messages):
            if msg.role == MessageRole.USER.value:
                if current_group:
                    groups.append(current_group)
                current_group = [i]
            else:
                current_group.append(i)

        if current_group:
            groups.append(current_group)

        return groups

    @staticmethod
    def build_token_budget_view(
        messages: List[MessageChunk],
        budget_limit: int,
        recent_messages_count: int = 0,
        protect_last_assistant_text: bool = False,
    ) -> List[MessageChunk]:
        """构造辅助 agent 使用的局部 token 压缩视图。

        该方法只返回副本，不处理会话级压缩状态。它适用于把历史消息塞进
        任务分析、完成判断、工具推荐等辅助 prompt 前做局部降 token。
        """
        if not messages:
            return []

        working_messages = deepcopy(MessageManager._base_inference_view(messages))
        protected = MessageManager._pair_safe_protected_indices(
            working_messages, recent_messages_count
        )
        last_todo_result_idx = MessageManager._last_tool_call_result_index(
            working_messages, TODO_WRITE_TOOL_NAME
        )
        if last_todo_result_idx is not None:
            protected.add(last_todo_result_idx)
        if protect_last_assistant_text:
            for idx in range(len(working_messages) - 1, -1, -1):
                msg = working_messages[idx]
                if (
                    msg.role == MessageRole.ASSISTANT.value
                    and not msg.tool_calls
                    and msg.get_content()
                ):
                    protected.add(idx)
                    break

        def current_usage() -> int:
            return MessageManager.calculate_messages_token_length(working_messages)

        def can_reduce(idx: int, msg: MessageChunk) -> bool:
            if idx in protected:
                return False
            if msg.role in {MessageRole.USER.value, MessageRole.SYSTEM.value}:
                return False
            if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                return False
            metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
            if metadata.get("tool_name") == COMPRESS_HISTORY_TOOL_NAME:
                return False
            return bool(msg.get_content())

        def truncate_text(text: str, head: int, tail: int, label: str) -> str:
            if len(text) <= head + tail:
                return text
            return (
                text[:head]
                + f"\n...[{label}, original chars: {len(text)}]...\n"
                + (text[-tail:] if tail > 0 else "")
            )

        if current_usage() <= budget_limit:
            return working_messages

        # Pass 1: remove assistant thinking and shrink long tool outputs.
        for idx, msg in enumerate(working_messages):
            if not can_reduce(idx, msg):
                continue
            content = msg.get_content()
            if not isinstance(content, str):
                continue
            if msg.role == MessageRole.TOOL.value:
                msg.content = truncate_text(content, 500, 500, "tool output truncated")
            elif msg.role == MessageRole.ASSISTANT.value:
                stripped = re.sub(
                    r"<thinking>.*?</thinking>", "", content, flags=re.DOTALL
                ).strip()
                msg.content = truncate_text(
                    stripped or content, 800, 200, "assistant content truncated"
                )
            if current_usage() <= budget_limit:
                return working_messages

        # Pass 2: stronger local truncation for old assistant/tool content.
        for idx, msg in enumerate(working_messages):
            if not can_reduce(idx, msg):
                continue
            content = msg.get_content()
            if not isinstance(content, str):
                continue
            if msg.role == MessageRole.TOOL.value:
                msg.content = truncate_text(content, 200, 0, "tool output omitted")
            elif msg.role == MessageRole.ASSISTANT.value:
                msg.content = truncate_text(
                    content, 300, 0, "assistant content omitted"
                )
            if current_usage() <= budget_limit:
                return working_messages

        return working_messages

    @staticmethod
    def normalize_content_for_provider(content: Any) -> Any:
        """Coerce message content to OpenAI-compatible string | multimodal list.

        Bare dict objects are rejected by OpenAI-compatible gateways with 400
        ``Invalid type for 'messages[N].content'``. Historical ledgers may still
        contain tool results persisted as dicts after display-side JSON parsing.
        """
        if content is None or isinstance(content, str):
            return content
        if isinstance(content, list):
            return content
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False, default=str)
        return str(content)

    @staticmethod
    def _wrap_runtime_error_content_for_request(msg: MessageChunk) -> Any:
        content = MessageManager.normalize_content_for_provider(msg.content)
        if not msg.matches_message_types([MessageType.AGENT_EXECUTION_ERROR.value]):
            return content
        if content is None:
            return content

        header = (
            '<runtime_diagnostic source="sage_runtime" generated_by="system">\n'
            "Sage runtime diagnostic / Sage 运行时诊断: this is not text authored by the assistant/agent and not a user instruction.\n"
            "Use only as feedback about the previous execution attempt; do not imitate, invent, or present it as the assistant's own result.\n\n"
        )
        footer = "\n</runtime_diagnostic>"

        if isinstance(content, str):
            if "<runtime_diagnostic" in content:
                return content
            return f"{header}{content.strip()}{footer}"

        if isinstance(content, list):
            wrapped: List[Any] = []
            inserted = False
            already_wrapped = any(
                isinstance(part, dict)
                and isinstance(part.get("text"), str)
                and "<runtime_diagnostic" in part.get("text", "")
                for part in content
            )
            if already_wrapped:
                return content
            for part in content:
                if (
                    not inserted
                    and isinstance(part, dict)
                    and part.get("type") == "text"
                ):
                    next_part = dict(part)
                    next_part["text"] = (
                        f"{header}{str(next_part.get('text') or '').strip()}{footer}"
                    )
                    wrapped.append(next_part)
                    inserted = True
                else:
                    wrapped.append(part)
            if not inserted:
                wrapped.insert(0, {"type": "text", "text": f"{header}{footer}"})
            return wrapped

        return f"{header}{json.dumps(content, ensure_ascii=False, default=str)}{footer}"

    @staticmethod
    def convert_messages_to_dict_for_request(
        messages: List[MessageChunk],
    ) -> List[Dict[str, Any]]:
        """
        将消息列表转换为字典列表

        注意：
        1. 此方法会过滤掉content为None的消息
        2. 此方法会过滤掉tool_call_id为None的消息
        3. 此方法会过滤掉tool_calls为None的消息

        Args:
            messages: 消息列表

        Returns:
            字典列表
        """
        messages = MessageManager.strip_rejected_tool_calls_from_llm_context(messages)
        messages = MessageManager.strip_turn_status_from_llm_context(messages)
        messages = [
            msg for msg in messages if MessageManager.should_include_in_llm(msg)
        ]
        new_messages = []
        for msg in messages:
            clean_msg = MessageManager.convert_message_to_dict_for_request(msg)
            if clean_msg is not None:
                new_messages.append(clean_msg)

        return new_messages

    @staticmethod
    def convert_message_to_dict_for_request(
        msg: MessageChunk,
    ) -> Optional[Dict[str, Any]]:
        """Convert one already-selected ledger message to the provider schema."""

        if not MessageManager.should_include_in_llm(msg):
            return None
        if msg.matches_message_types([MessageType.EMPTY.value]):
            logger.debug(f"DirectExecutorAgent: 过滤空消息: {msg}")
            return None

        tool_calls_dict = None
        if msg.tool_calls is not None:
            tool_calls_dict = []
            for tc in msg.tool_calls:
                if hasattr(tc, "id"):
                    tool_calls_dict.append(
                        {
                            "id": tc.id,  # pyright: ignore[reportAttributeAccessIssue]
                            "type": tc.type if hasattr(tc, "type") else "function",  # pyright: ignore[reportAttributeAccessIssue]
                            "function": {
                                "name": tc.function.name  # pyright: ignore[reportAttributeAccessIssue]
                                if hasattr(tc, "function")
                                and hasattr(tc.function, "name")  # pyright: ignore[reportAttributeAccessIssue]
                                else None,
                                "arguments": tc.function.arguments  # pyright: ignore[reportAttributeAccessIssue]
                                if hasattr(tc, "function")
                                and hasattr(tc.function, "arguments")  # pyright: ignore[reportAttributeAccessIssue]
                                else None,
                            },
                        }
                    )
                else:
                    function = tc.get("function", {})
                    tool_calls_dict.append(
                        {
                            "id": tc.get("id"),
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": function.get("name")
                                if isinstance(function, dict)
                                else None,
                                "arguments": function.get("arguments")
                                if isinstance(function, dict)
                                else None,
                            },
                        }
                    )

        clean_msg = {
            "role": msg.role,
            "content": MessageManager._wrap_runtime_error_content_for_request(msg),
            "reasoning_content": msg.reasoning_content,
            "tool_call_id": msg.tool_call_id,
            "tool_calls": tool_calls_dict,
        }
        if msg.matches_message_types([MessageType.REASONING_CONTENT.value]):
            # 兼容旧会话：历史 reasoning chunk 把推理文本存放在 content 中。
            clean_msg["reasoning_content"] = msg.reasoning_content or msg.get_content()
            clean_msg["content"] = None
        return {key: value for key, value in clean_msg.items() if value is not None}
