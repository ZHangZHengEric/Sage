"""Request-scoped prompt token accounting.

Provider usage is authoritative only for a complete request.  This module keeps
that request-level truth separate from per-message estimates and stores only
hashes and numeric estimates; prompt contents are never persisted here.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
import time
import unicodedata
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
)


ACCOUNTING_SCHEMA_VERSION = 1
DEFAULT_COMPRESSION_THRESHOLD = 0.85
MAX_CHECKPOINTS_PER_SESSION = 32
MIN_CHECKPOINT_OVERLAP = 0.5
MAX_DYNAMIC_SCALE = 8.0
_LONG_ASCII_TOKEN_RUN = re.compile(r"[A-Za-z0-9_+/=-]{32,}")


class InferenceViewMessageTokenReport(TypedDict):
    message_id: Optional[str]
    fingerprint: str
    estimated_tokens: int
    cumulative_estimated_tokens: int


class InferenceViewTokenReport(TypedDict):
    view_spec_hash: str
    messages: List[InferenceViewMessageTokenReport]
    total_estimated_tokens: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _static_text_tokens(value: str) -> int:
    total = 0.0
    for char in value:
        if "\u4e00" <= char <= "\u9fff":
            total += 0.6
        elif char.isalpha():
            total += 0.25
        elif char.isdigit():
            total += 0.2
        else:
            total += 0.4
    return max(1, math.ceil(total)) if value else 0


def _conservative_text_tokens(value: str) -> int:
    """Estimate an upper-risk budget without assuming a model tokenizer.

    This is deliberately content-aware: ordinary ASCII prose keeps a small
    margin, while CJK, emoji and long opaque ASCII runs receive substantially
    more room. It is still an estimate -- provider usage remains authoritative.
    """
    if not value:
        return 0

    total = 0.0
    for char in value:
        if char.isascii():
            if char.isspace():
                total += 0.1
            elif char.isdigit():
                total += 0.4
            elif char.isalpha() or char == "_":
                total += 0.28
            else:
                total += 0.5
            continue

        category = unicodedata.category(char)
        if unicodedata.east_asian_width(char) in {"W", "F"} and category[0] in {
            "L",
            "N",
        }:
            total += 2.0
        elif category[0] in {"L", "N"}:
            total += 1.0
        else:
            # Emoji and uncommon symbols often split into several tokens. UTF-8
            # width is a portable conservative signal when the tokenizer is unknown.
            total += max(1, len(char.encode("utf-8")))

    # Random identifiers, hashes and base64-like payloads tokenize much more
    # densely than prose. Raise only the contribution of those opaque runs.
    for match in _LONG_ASCII_TOKEN_RUN.finditer(value):
        run = match.group(0)
        ordinary = sum(0.4 if char.isdigit() else 0.28 for char in run)
        total += max(0.0, len(run) * 0.8 - ordinary)

    return max(1, math.ceil(total))


def _accounting_value(value: Any) -> Tuple[Any, int]:
    """Return a base64-safe value plus image-token estimate."""
    image_tokens = 0

    def visit(item: Any) -> Any:
        nonlocal image_tokens
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, dict):
            if item.get("type") == "image_url":
                image_url = item.get("image_url", {})
                url = (
                    image_url.get("url", "")
                    if isinstance(image_url, dict)
                    else str(image_url)
                )
                if isinstance(url, str) and url.startswith("data:"):
                    payload = url.split(",", 1)[-1]
                    estimated = min(max(500, int(len(payload) * 0.2)), 3000)
                    image_tokens += estimated
                    safe_url = {
                        "data_sha256": hashlib.sha256(
                            payload.encode("utf-8")
                        ).hexdigest(),
                        "data_length": len(payload),
                    }
                else:
                    image_tokens += 1000
                    safe_url = url
                copied = {key: visit(val) for key, val in item.items()}
                copied["image_url"] = safe_url
                return copied
            return {str(key): visit(val) for key, val in item.items()}
        return item

    return visit(value), image_tokens


@dataclass(frozen=True)
class ContextViewSpec:
    policy_id: str = "default"
    recent_turns: int = 0
    allowed_message_types: Tuple[str, ...] = ()
    include_compression_anchors: bool = True
    protected_message_ids: Tuple[str, ...] = ()
    persistent_history: bool = False

    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


class ContextOverflowStrategy(str, Enum):
    PASSTHROUGH = "passthrough"
    PERSISTENT_SUMMARY = "persistent_summary"


@dataclass(frozen=True)
class ContextPolicy:
    view_spec: ContextViewSpec = field(default_factory=ContextViewSpec)
    overflow_strategy: ContextOverflowStrategy = ContextOverflowStrategy.PASSTHROUGH
    protect_latest_user: bool = True
    protect_extra_messages: bool = True
    persistent_compressor: Optional[Any] = None


@dataclass(frozen=True)
class PromptComponent:
    kind: str
    fingerprint: str
    estimated_tokens: int
    conservative_tokens: int
    message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PromptComponent":
        return cls(
            kind=str(value.get("kind") or "message"),
            fingerprint=str(value.get("fingerprint") or ""),
            estimated_tokens=max(0, int(value.get("estimated_tokens") or 0)),
            conservative_tokens=max(
                0,
                int(
                    value.get("conservative_tokens")
                    or value.get("estimated_tokens")
                    or 0
                ),
            ),
            message_id=(
                str(value.get("message_id")) if value.get("message_id") else None
            ),
        )


@dataclass
class PromptTokenManifest:
    components: List[PromptComponent]

    @property
    def estimated_tokens(self) -> int:
        return sum(component.estimated_tokens for component in self.components)

    @property
    def conservative_tokens(self) -> int:
        return sum(component.conservative_tokens for component in self.components)


@dataclass
class PromptTokenProjection:
    projected_tokens: int
    source: str
    profile_id: str
    full_estimate: int
    conservative_estimate: int
    actual_prompt_tokens: Optional[int] = None
    added_estimated_tokens: int = 0
    removed_estimated_tokens: int = 0
    matched_estimated_tokens: int = 0
    overlap_ratio: float = 0.0
    scale: float = 1.0
    fallback_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromptTokenCheckpoint:
    profile_id: str
    actual_prompt_tokens: int
    estimated_prompt_tokens: int
    components: List[PromptComponent]
    version: int = ACCOUNTING_SCHEMA_VERSION
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["components"] = [item.to_dict() for item in self.components]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Optional["PromptTokenCheckpoint"]:
        try:
            if int(value.get("version") or 0) != ACCOUNTING_SCHEMA_VERSION:
                return None
            profile_id = str(value.get("profile_id") or "")
            actual = int(value.get("actual_prompt_tokens") or 0)
            estimated = int(value.get("estimated_prompt_tokens") or 0)
            raw_components = value.get("components") or []
            if not profile_id or actual <= 0 or estimated <= 0:
                return None
            if not isinstance(raw_components, list):
                return None
            components = [
                PromptComponent.from_dict(item)
                for item in raw_components
                if isinstance(item, Mapping)
            ]
            if not components:
                return None
            return cls(
                profile_id=profile_id,
                actual_prompt_tokens=actual,
                estimated_prompt_tokens=estimated,
                components=components,
                version=ACCOUNTING_SCHEMA_VERSION,
                created_at=float(value.get("created_at") or time.time()),
                last_used_at=float(value.get("last_used_at") or time.time()),
            )
        except (TypeError, ValueError):
            return None


class PromptTokenEstimator:
    """Deterministic component estimator used for full and delta estimates."""

    @staticmethod
    def component(
        kind: str, value: Any, message_id: Optional[str] = None
    ) -> PromptComponent:
        safe_value, image_tokens = _accounting_value(value)
        serialized = _canonical_json(safe_value)
        # Canonical JSON includes role/tool framing; two tokens cover the provider's
        # per-component separators without pretending to be an exact tokenizer.
        estimated = _static_text_tokens(serialized) + image_tokens + 2
        conservative = max(
            estimated,
            _conservative_text_tokens(serialized) + image_tokens + 2,
        )
        return PromptComponent(
            kind=kind,
            fingerprint=_fingerprint(safe_value),
            estimated_tokens=max(1, estimated),
            conservative_tokens=max(1, conservative),
            message_id=message_id,
        )

    @classmethod
    def manifest(
        cls,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Any = None,
        response_format: Any = None,
    ) -> PromptTokenManifest:
        components: List[PromptComponent] = []
        for message in messages:
            message_id = message.get("_sage_message_id") or message.get("message_id")
            kind = "system" if message.get("role") == "system" else "message"
            token_value = {
                key: val
                for key, val in message.items()
                if key
                in {
                    "role",
                    "content",
                    "reasoning_content",
                    "tool_calls",
                    "tool_call_id",
                }
            }
            components.append(
                cls.component(
                    kind,
                    token_value,
                    message_id=str(message_id) if message_id else None,
                )
            )
        if tools:
            components.append(cls.component("tools", tools))
        if response_format:
            components.append(cls.component("response_format", response_format))
        return PromptTokenManifest(components)


class PromptBudgetManager:
    """Per-session request checkpoints and prompt-size projections."""

    def __init__(self, checkpoints: Optional[Mapping[str, Any]] = None):
        self._checkpoints: "OrderedDict[str, PromptTokenCheckpoint]" = OrderedDict()
        self.restore(checkpoints or {})

    @staticmethod
    def build_profile_id(
        *,
        model: str,
        provider_identity: str,
        agent_class: str,
        step_name: str,
        view_policy_id: str,
    ) -> str:
        return _fingerprint(
            {
                "version": ACCOUNTING_SCHEMA_VERSION,
                "model": str(model or "").strip().lower(),
                "provider": str(provider_identity or "").strip().lower(),
                "agent_class": str(agent_class or "").strip(),
                "step_name": str(step_name or "").strip(),
                "view_policy_id": str(view_policy_id or "").strip(),
            }
        )

    @staticmethod
    def input_limit(
        max_model_len: int,
        compression_threshold: float,
        max_model_input_len: Optional[int] = None,
    ) -> int:
        if not 0 < float(compression_threshold) < 1:
            raise ValueError(
                "compression_threshold must be greater than 0 and less than 1"
            )
        percentage_limit = math.floor(int(max_model_len) * float(compression_threshold))
        if max_model_input_len is None:
            return percentage_limit
        return min(percentage_limit, int(max_model_input_len))

    @staticmethod
    def _component_counter(
        components: Iterable[PromptComponent],
    ) -> Counter[Tuple[str, str, int, int]]:
        return Counter(
            (
                item.kind,
                item.fingerprint,
                item.estimated_tokens,
                item.conservative_tokens,
            )
            for item in components
        )

    def project(
        self, profile_id: str, manifest: PromptTokenManifest
    ) -> PromptTokenProjection:
        full_estimate = manifest.estimated_tokens
        conservative_estimate = manifest.conservative_tokens
        checkpoint = self._checkpoints.get(profile_id)
        if checkpoint is None:
            return PromptTokenProjection(
                # The compression threshold is already a safety margin.  Using
                # the tokenizer-agnostic worst-case bound here made proactive
                # compression fire far too early for CJK, emoji and opaque
                # identifiers.  Keep that bound as diagnostics, but let the
                # ordinary estimate drive the soft trigger until provider usage
                # gives this request profile a calibrated baseline.
                projected_tokens=full_estimate,
                source="full_estimate",
                profile_id=profile_id,
                full_estimate=full_estimate,
                conservative_estimate=conservative_estimate,
                fallback_reason="checkpoint_missing",
            )

        old_counter = self._component_counter(checkpoint.components)
        new_counter = self._component_counter(manifest.components)
        matched = old_counter & new_counter
        added = new_counter - old_counter
        removed = old_counter - new_counter

        matched_tokens = sum(key[2] * count for key, count in matched.items())
        added_tokens = sum(key[2] * count for key, count in added.items())
        removed_tokens = sum(key[2] * count for key, count in removed.items())
        overlap = matched_tokens / max(1, checkpoint.estimated_prompt_tokens)
        if overlap < MIN_CHECKPOINT_OVERLAP:
            return PromptTokenProjection(
                projected_tokens=full_estimate,
                source="full_estimate",
                profile_id=profile_id,
                full_estimate=full_estimate,
                conservative_estimate=conservative_estimate,
                actual_prompt_tokens=checkpoint.actual_prompt_tokens,
                matched_estimated_tokens=matched_tokens,
                overlap_ratio=overlap,
                fallback_reason="checkpoint_low_overlap",
            )

        scale = max(
            0.5,
            min(
                MAX_DYNAMIC_SCALE,
                checkpoint.actual_prompt_tokens
                / max(1, checkpoint.estimated_prompt_tokens),
            ),
        )
        dynamic_projection = math.ceil(
            checkpoint.actual_prompt_tokens
            + scale * added_tokens
            - scale * removed_tokens
        )
        unchanged = not added and not removed
        projected = (
            checkpoint.actual_prompt_tokens if unchanged else dynamic_projection
        )
        checkpoint.last_used_at = time.time()
        self._checkpoints.move_to_end(profile_id)
        return PromptTokenProjection(
            projected_tokens=max(0, projected),
            source="actual_delta",
            profile_id=profile_id,
            full_estimate=full_estimate,
            conservative_estimate=conservative_estimate,
            actual_prompt_tokens=checkpoint.actual_prompt_tokens,
            added_estimated_tokens=added_tokens,
            removed_estimated_tokens=removed_tokens,
            matched_estimated_tokens=matched_tokens,
            overlap_ratio=overlap,
            scale=scale,
        )

    def update_checkpoint(
        self,
        profile_id: str,
        actual_prompt_tokens: int,
        manifest: PromptTokenManifest,
    ) -> None:
        if actual_prompt_tokens <= 0 or manifest.estimated_tokens <= 0:
            return
        now = time.time()
        self._checkpoints[profile_id] = PromptTokenCheckpoint(
            profile_id=profile_id,
            actual_prompt_tokens=int(actual_prompt_tokens),
            estimated_prompt_tokens=manifest.estimated_tokens,
            components=list(manifest.components),
            created_at=now,
            last_used_at=now,
        )
        self._checkpoints.move_to_end(profile_id)
        while len(self._checkpoints) > MAX_CHECKPOINTS_PER_SESSION:
            self._checkpoints.popitem(last=False)

    def clear(self) -> None:
        self._checkpoints.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            profile_id: checkpoint.to_dict()
            for profile_id, checkpoint in self._checkpoints.items()
        }

    def restore(self, checkpoints: Mapping[str, Any]) -> None:
        self._checkpoints.clear()
        if not isinstance(checkpoints, Mapping):
            return
        restored: List[PromptTokenCheckpoint] = []
        for value in checkpoints.values():
            if not isinstance(value, Mapping):
                continue
            checkpoint = PromptTokenCheckpoint.from_dict(value)
            if checkpoint is not None:
                restored.append(checkpoint)
        restored.sort(key=lambda item: item.last_used_at)
        for checkpoint in restored[-MAX_CHECKPOINTS_PER_SESSION:]:
            self._checkpoints[checkpoint.profile_id] = checkpoint
