from typing import Callable, Any, Dict, Optional
from sagents.utils.logger import logger

class ConditionRegistry:
    _registry: Dict[str, Callable[[Any], bool]] = {}

    @classmethod
    def register(cls, name: str):
        """装饰器：注册一个条件检查函数"""
        def decorator(func: Callable[[Any], bool]):
            if name in cls._registry:
                logger.warning(f"ConditionRegistry: Overwriting existing condition '{name}'")
            cls._registry[name] = func
            return func
        return decorator

    @classmethod
    def check(cls, name: str, context: Any, session: Any = None) -> bool:
        """检查条件是否满足"""
        if name not in cls._registry:
            logger.warning(f"ConditionRegistry: Condition '{name}' not found, defaulting to False")
            return False
        try:
            return cls._registry[name](context, session=session)
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
    last_msg_role = last_msg.role if isinstance(last_msg, MessageChunk) else last_msg.get("role")
    
    # 如果强制总结开启，或者最后是工具调用，则需要总结
    force_summary = session_context.audit_status.get("force_summary", False)
    if not (force_summary or last_msg_role == MessageRole.TOOL.value):
        return False

    # turn_status 是协议性工具而非任务执行工具，调用前模型已输出自然语言说明，
    # 无需再次触发 TaskSummaryAgent，否则会在 need_user_input/blocked/task_done
    # 之后多余地生成一条 final_answer。force_summary=True 时不受此限制。
    if last_msg_role == MessageRole.TOOL.value and not force_summary:
        content = last_msg.content if isinstance(last_msg, MessageChunk) else last_msg.get("content", "")
        if isinstance(content, str):
            try:
                content_dict = json.loads(content)
                if isinstance(content_dict, dict):
                    # 旧版成功体含 turn_status；新版仅 {"should_end": bool}。错误体含 success==False，不当作协议成功。
                    if "turn_status" in content_dict:
                        return False
                    if "should_end" in content_dict and content_dict.get("success") is not False:
                        return False
            except (json.JSONDecodeError, TypeError):
                pass

    return True

@ConditionRegistry.register("task_not_completed")
def check_task_not_completed(session_context, session=None) -> bool:
    """检查多智能体任务是否尚未全部完成"""
    from sagents.context.session_context import SessionStatus
    
    # 1. 检查是否已进入终态
    if session:
        session_status = session.get_status()
        if session_status in {
            SessionStatus.INTERRUPTED,
            SessionStatus.COMPLETED,
            SessionStatus.ERROR,
        }:
            return False

    # 2. 检查是否被中断
    if session and session.get_status() == SessionStatus.INTERRUPTED:
        return False

    # 如果自检失败，必须继续循环修复，不能被旧的 completion_status 短路。
    if session_context.audit_status.get("self_check_passed") is False:
        logger.info("SAgent: 检测到 self_check 失败，继续循环修复")
        return True
        
    # 3. 检查审计状态中的完成标志
    if session_context.audit_status.get("task_completed", False):
        logger.info(f"SAgent: 检测到 task_completed 标志，任务结束")
        return False
        
    # 4. 检查 completion_status
    status = session_context.audit_status.get("completion_status")
    if status in ["completed", "need_user_input", "failed"]:
        logger.info(f"SAgent: 检测到 completion_status={status}，任务结束")
        return False
        
    # 5. 检查待办任务列表 (如果存在)
    # 尝试从 system_context 获取 todo_list
    todo_list = session_context.system_context.get("todo_list", [])
    if todo_list:
        pending_tasks = [t for t in todo_list if (t.get("status") or "pending") != "completed"]
        if not pending_tasks:
            logger.info("SAgent: 所有任务已标记完成")
            # 如果确实有任务列表且都完成了，也可以视为结束
            # 但通常 completion_status 会由 Judge Agent 设置，所以这里仅作为辅助判断
            # 如果 Judge 还没运行，可能状态还没更新，所以主要依赖 completion_status
            pass
            
    return True

@ConditionRegistry.register("always_true")
def always_true(session_context, session=None) -> bool:
    return True

@ConditionRegistry.register("always_false")
def always_false(session_context, session=None) -> bool:
    return False
