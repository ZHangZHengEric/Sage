from typing import Callable, Any, Dict
from sagents.utils.logger import logger


class ConditionRegistry:
    _registry: Dict[str, Callable[[Any], bool]] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册一个条件检查函数"""

        def decorator(func: Callable[[Any], bool]):
            if name in cls._registry:
                logger.warning(
                    f"ConditionRegistry: Overwriting existing condition '{name}'"
                )
            cls._registry[name] = func
            return func

        return decorator

    @classmethod
    def check(cls, name: str, context: Any, session: Any = None) -> bool:
        """检查条件是否满足"""
        if name not in cls._registry:
            logger.warning(
                f"ConditionRegistry: Condition '{name}' not found, defaulting to False"
            )
            return False
        try:
            return cls._registry[name](context, session=session)  # pyright: ignore[reportCallIssue]
        except Exception as e:
            logger.error(f"ConditionRegistry: Error checking condition '{name}': {e}")
            return False

    @classmethod
    def list_conditions(cls):
        return list(cls._registry.keys())


# --- 预置条件 ---


@ConditionRegistry.register("is_deep_thinking")
def check_deep_thinking(session_context, session=None) -> bool:
    """检查是否启用了深度思考模式"""
    return session_context.audit_status.get("deep_thinking", False)


@ConditionRegistry.register("enable_more_suggest")
def check_more_suggest(session_context, session=None) -> bool:
    """检查是否启用了更多建议"""
    # 这个状态通常存在 audit_status 或者 system_context 中，这里假设在 audit_status
    # 如果没有，可能需要在 SessionContext 中维护
    return session_context.audit_status.get("more_suggest", False)


@ConditionRegistry.register("enable_plan")
def check_enable_plan(session_context, session=None) -> bool:
    """检查是否启用了规划阶段"""
    return session_context.audit_status.get("enable_plan", False)


@ConditionRegistry.register("plan_should_start_execution")
def check_plan_should_start_execution(session_context, session=None) -> bool:
    """检查规划阶段是否已经决定进入正式执行"""
    return session_context.audit_status.get("plan_status") == "start_execution"


@ConditionRegistry.register("self_check_should_retry")
def check_self_check_should_retry(session_context, session=None) -> bool:
    """检查是否需要继续执行并重新通过自检。"""
    from sagents.context.session_context import SessionStatus

    if session and session.get_status() == SessionStatus.INTERRUPTED:
        return False
    return session_context.audit_status.get("self_check_passed") is not True


@ConditionRegistry.register("need_summary")
def check_need_summary(session_context, session=None) -> bool:
    """检查是否需要总结（例如最后一条消息是工具调用）"""
    import json
    from sagents.context.messages.message import MessageChunk, MessageRole

    if not session_context.message_manager.messages:
        return False

    last_msg = session_context.message_manager.messages[-1]
    last_msg_role = (
        last_msg.role if isinstance(last_msg, MessageChunk) else last_msg.get("role")
    )

    # 如果强制总结开启，或者最后是工具调用，则需要总结
    force_summary = session_context.audit_status.get("force_summary", False)
    if not (force_summary or last_msg_role == MessageRole.TOOL.value):
        return False

    # turn_status 是协议性工具而非任务执行工具，调用前模型已输出自然语言说明，
    # 无需再触发额外总结，否则会在 need_user_input/blocked/task_done
    # 之后多余地生成一条 final_answer。force_summary=True 时不受此限制。
    if last_msg_role == MessageRole.TOOL.value and not force_summary:
        content = (
            last_msg.content
            if isinstance(last_msg, MessageChunk)
            else last_msg.get("content", "")
        )
        if isinstance(content, str):
            try:
                content_dict = json.loads(content)
                if isinstance(content_dict, dict):
                    # 旧版成功体含 turn_status；新版仅 {"should_end": bool}。错误体含 success==False，不当作协议成功。
                    if "turn_status" in content_dict:
                        return False
                    if (
                        "should_end" in content_dict
                        and content_dict.get("success") is not False
                    ):
                        return False
            except (json.JSONDecodeError, TypeError):
                pass

    return True


@ConditionRegistry.register("always_true")
def always_true(session_context, session=None) -> bool:
    return True


@ConditionRegistry.register("always_false")
def always_false(session_context, session=None) -> bool:
    return False
