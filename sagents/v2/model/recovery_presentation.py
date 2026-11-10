"""Deterministic user-facing model failure summaries, independent of LLM availability."""

from sagents.v2.model.recovery_policy import failure_from_error

_MESSAGES = {
    "empty": (
        "The model returned no usable answer after recovery.",
        "模型恢复后仍未返回可用回答。",
    ),
    "reasoning_only": (
        "The model did not produce a deliverable answer after recovery.",
        "模型恢复后仍未给出可交付的回答。",
    ),
    "quota": (
        "The model service quota or balance is exhausted. Check billing or quota settings.",
        "模型服务额度或余额不足，请检查额度及计费设置。",
    ),
    "authentication": (
        "The model service rejected the credentials. Check the configured credential.",
        "模型服务鉴权失败，请检查凭据配置。",
    ),
    "permission": (
        "The model service denied access. Check model access and service permissions.",
        "模型服务拒绝访问，请检查模型权限及服务限制。",
    ),
    "rate_limit": (
        "The model service is rate limited and automatic recovery has stopped.",
        "模型服务触发限流，自动恢复已停止。",
    ),
    "transport": (
        "The model connection failed and automatic recovery has stopped.",
        "模型连接异常，自动恢复已停止。",
    ),
    "stream": (
        "The model response was interrupted and automatic recovery has stopped.",
        "模型响应中断，自动恢复已停止。",
    ),
    "overloaded": (
        "The model service is unavailable and automatic recovery has stopped.",
        "模型服务暂时不可用，自动恢复已停止。",
    ),
    "refused": (
        "The model declined or filtered the response.",
        "模型拒绝了请求或响应被服务端过滤。",
    ),
    "paused": (
        "This route cannot safely continue the provider's paused response.",
        "当前路由无法安全续接服务端暂停的响应。",
    ),
    "protocol": (
        "The model returned an unsupported or invalid protocol response.",
        "模型返回了不支持或无效的协议响应。",
    ),
    "arguments": (
        "The model could not generate valid tool arguments within the recovery budget.",
        "模型未能在恢复预算内生成有效工具参数。",
    ),
}

_MESSAGES.update(
    {
        "route": (
            "The configured model or endpoint was not found.",
            "未找到配置的模型或接口，请检查路由设置。",
        ),
        "invalid_request": (
            "The model request is incompatible with this route; no verified repair is available.",
            "模型请求与当前路由不兼容，暂无可验证的自动修复方案。",
        ),
        "context": (
            "The input exceeded the model context limit and could not be reduced safely.",
            "输入超过模型上下文限制，无法继续安全压缩。",
        ),
        "payload": (
            "The request or media exceeded the service size limit.",
            "请求或媒体超过服务大小限制。",
        ),
        "media": (
            "Required media could not be used; check its format and availability.",
            "所需媒体无法使用，请检查格式及可访问性。",
        ),
        "output_limit": (
            "The model output limit prevented completion within the recovery budget.",
            "模型输出达到上限，未能在恢复预算内完成。",
        ),
        "structured_output": (
            "The model did not meet the required output format within the recovery budget.",
            "模型未能在恢复预算内满足输出格式要求。",
        ),
        "unsupported": (
            "This model route returned an unsupported protocol feature.",
            "模型路由返回了当前不支持的协议功能。",
        ),
        "state": (
            "Provider state cannot be safely restored; uncertain operations will not be repeated.",
            "无法安全还原模型状态，未重复执行结果不确定的操作。",
        ),
        "capacity": (
            "The model queue could not accept the request within the waiting budget.",
            "模型队列未能在等待预算内接受请求。",
        ),
        "budget": ("The model recovery budget is exhausted.", "模型恢复预算已耗尽。"),
        "cancelled": ("The model call was cancelled.", "模型调用已取消。"),
        "internal": (
            "An internal model processing error stopped the run. Use the correlation ID for diagnosis.",
            "模型处理发生内部异常，执行已停止，可通过关联 ID 排查。",
        ),
        "unknown": (
            "An unrecognized model error stopped automatic recovery. Use the correlation ID for diagnosis.",
            "模型发生未识别的异常，自动恢复已停止，可通过关联 ID 排查。",
        ),
    }
)


def failure_presentation(
    error, *, language="en", tool_call_ids=(), correlation_id=None
):
    failure = failure_from_error(error)
    zh = language.lower().startswith("zh")
    pair = _MESSAGES.get(failure.kind.value)
    message = pair[int(zh)] if pair else error.message
    if failure.kind.value == "refused" and error.metadata.get("refusal_text"):
        message += " " + str(error.metadata["refusal_text"])[:2000]
    if tool_call_ids:
        message += (
            " 已记录的工具结果已保留；本次执行未正常完成。"
            if zh
            else " Recorded tool results are preserved; this run did not complete."
        )
    return {
        "version": "model-failure-summary/1",
        "message": message,
        "phase": failure.phase,
        "kind": failure.kind.value,
        "preserved_tool_call_ids": list(dict.fromkeys(tool_call_ids)),
        "correlation_id": correlation_id,
        "recovery": error.metadata.get("recovery", {}),
        "next_action": "check_configuration"
        if failure.kind.value
        in {"quota", "authentication", "permission", "route", "invalid_request"}
        else "review_preserved_results",
    }
