use anyhow::Result;
use serde_json::json;

use crate::app::{App, MessageKind};
use crate::backend::{BackendHandle, BackendRequest, BackendRuntime, V2InputRequest};
use crate::terminal::ensure_backend;

pub(super) fn run_task(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    task: String,
) -> Result<bool> {
    if let Some(pending) = app.pending_v2_input.clone() {
        // v2 正在等一个非审批交互的回答：composer 输入就是答案，不是新任务。
        return answer_v2_input(app, backend, pending, task);
    }
    let request = BackendRequest {
        runtime: app.runtime,
        resume_session: app.v2_session_known,
        session_id: app.session_id.clone(),
        user_id: app.user_id.clone(),
        agent_config: app.agent_config_path.clone(),
        agent_id: if app.agent_config_path.is_some() {
            None
        } else {
            app.selected_agent_id.clone()
        },
        agent_mode: if app.agent_config_path.is_none() || app.agent_mode_override {
            Some(app.agent_mode.clone())
        } else {
            None
        },
        max_loop_count: if app.agent_config_path.is_none() {
            Some(app.max_loop_count)
        } else {
            None
        },
        workspace: app.workspace_override_path().map(|path| path.to_path_buf()),
        sandbox_type: app.sandbox_type.clone(),
        sandbox_approval_mode: app.sandbox_approval_mode.clone(),
        skills: app.selected_skills.clone(),
        model_override: app.selected_model.clone(),
        goal_objective: app
            .pending_goal_mutation
            .as_ref()
            .and_then(|goal| goal.objective.clone()),
        goal_status: app
            .pending_goal_mutation
            .as_ref()
            .and_then(|goal| goal.status.clone()),
        clear_goal: app
            .pending_goal_mutation
            .as_ref()
            .map(|goal| goal.clear)
            .unwrap_or(false),
        task,
    };
    let handle = ensure_backend(backend, &request)?;
    handle.send_prompt(&request.task)?;
    Ok(true)
}

/// v2 Run 进行中的输入：以 `v2_steer` 帧交给后端；后端用 `cli_v2_steer` 回报接受/拒绝。
pub(super) fn steer_task(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    text: String,
) -> Result<bool> {
    let Some(handle) = backend.as_ref() else {
        app.push_message(
            MessageKind::System,
            "backend unavailable; no run is active to steer",
        );
        app.set_status(format!("ready  {}", app.session_id));
        return Ok(true);
    };
    if handle.runtime() != BackendRuntime::V2 {
        // 只有 v2 才有 steer；v1 后端把运行中的输入当下一条 prompt。
        handle.send_prompt(&text)?;
        return Ok(true);
    }
    handle.send_v2_steer(&text)?;
    app.set_status(format!("steer sent  {}", app.session_id));
    Ok(true)
}

pub(super) fn interrupt_task(app: &mut App, backend: &mut Option<BackendHandle>) -> Result<bool> {
    if !app.busy {
        app.push_message(
            crate::app::MessageKind::System,
            "no active request to interrupt",
        );
        app.set_status(format!("ready  {}", app.session_id));
        return Ok(true);
    }

    if let Some(handle) = backend.take() {
        handle.stop();
    }
    app.interrupt_request();
    Ok(true)
}

pub(super) fn retry_last_task(app: &mut App, backend: &mut Option<BackendHandle>) -> Result<bool> {
    if app.busy {
        app.push_message(
            crate::app::MessageKind::System,
            "request still running; use /interrupt before /retry",
        );
        app.set_status(format!("busy  {}", app.session_id));
        return Ok(true);
    }

    let Some(task) = app.last_submitted_task.clone() else {
        app.push_message(
            crate::app::MessageKind::System,
            "no previous task available to retry",
        );
        app.set_status(format!("retry unavailable  {}", app.session_id));
        return Ok(true);
    };

    app.begin_task_submission(task.clone(), true);
    let result = run_task(app, backend, task);
    if result.is_ok() {
        app.clear_pending_sandbox_approval();
    }
    result
}

pub(super) fn approve_sandbox_command(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
) -> Result<bool> {
    if app.pending_sandbox_approval.is_none() {
        if let Some(pending) = app.pending_v2_input.clone() {
            return answer_v2_input_with_decision(
                app,
                backend,
                &pending,
                &["retry", "confirm_succeeded"],
            );
        }
    }
    let Some(request) = app.pending_sandbox_approval.clone() else {
        app.push_message(
            crate::app::MessageKind::System,
            "no pending sandbox approval",
        );
        app.set_status(format!("approval unavailable  {}", app.session_id));
        return Ok(true);
    };

    let Some(handle) = backend.as_ref() else {
        app.push_message(
            crate::app::MessageKind::System,
            "backend unavailable for sandbox approval",
        );
        app.set_status(format!("approval unavailable  {}", app.session_id));
        return Ok(true);
    };

    handle.send_sandbox_approval_decision(
        &app.session_id,
        &request.approval_id,
        request.command_hash.as_deref(),
        "approve",
    )?;
    app.push_message(
        crate::app::MessageKind::Tool,
        format!(
            "sandbox approval sent\napproval_id: {}",
            request.approval_id
        ),
    );
    app.set_status(format!("approval sent  {}", app.session_id));
    Ok(true)
}

fn answer_v2_input(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    pending: V2InputRequest,
    text: String,
) -> Result<bool> {
    // 直接输入一个允许的决定名（如 reconcile / mark_failed）就按该决定回答。
    let typed = text.trim();
    if pending
        .allowed_decisions
        .iter()
        .any(|decision| decision == typed)
    {
        return answer_v2_input_with_decision(app, backend, &pending, &[typed]);
    }
    let decision = if pending
        .allowed_decisions
        .iter()
        .any(|value| value == "submit")
    {
        "submit"
    } else if pending
        .allowed_decisions
        .iter()
        .any(|value| value == "change_direction")
    {
        "change_direction"
    } else {
        app.push_message(
            MessageKind::System,
            "the pending question does not accept free text; use /approve or /deny",
        );
        app.set_status(format!("input required  {}", app.session_id));
        return Ok(true);
    };
    let Some(handle) = backend.as_ref() else {
        app.push_message(
            MessageKind::System,
            "backend unavailable to answer the question",
        );
        return Ok(true);
    };
    handle.send_v2_interaction_decision(
        &pending.interaction_id,
        decision,
        json!({ "text": text }),
    )?;
    app.pending_v2_input = None;
    app.push_message(MessageKind::Tool, format!("answer sent ({decision})"));
    app.set_status(format!("answer sent  {}", app.session_id));
    Ok(true)
}

fn answer_v2_input_with_decision(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    pending: &V2InputRequest,
    preferred: &[&str],
) -> Result<bool> {
    let Some(decision) = preferred.iter().copied().find(|candidate| {
        pending
            .allowed_decisions
            .iter()
            .any(|value| value == candidate)
    }) else {
        app.push_message(
            MessageKind::System,
            format!(
                "the pending question accepts: {}",
                pending.allowed_decisions.join(", ")
            ),
        );
        return Ok(true);
    };
    let Some(handle) = backend.as_ref() else {
        app.pending_v2_input = None;
        app.push_message(
            MessageKind::System,
            "backend unavailable to answer the question",
        );
        return Ok(true);
    };
    handle.send_v2_interaction_decision(&pending.interaction_id, decision, json!({}))?;
    app.pending_v2_input = None;
    app.push_message(MessageKind::Tool, format!("answer sent ({decision})"));
    app.set_status(format!("answer sent  {}", app.session_id));
    Ok(true)
}

pub(super) fn remember_sandbox_command(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
) -> Result<bool> {
    let Some(request) = app.pending_sandbox_approval.clone() else {
        app.push_message(MessageKind::System, "no pending sandbox approval");
        app.set_status(format!("approval unavailable  {}", app.session_id));
        return Ok(true);
    };
    let Some(handle) = backend.as_ref() else {
        app.push_message(
            MessageKind::System,
            "backend unavailable for sandbox approval",
        );
        app.set_status(format!("approval unavailable  {}", app.session_id));
        return Ok(true);
    };
    if handle.runtime() != BackendRuntime::V2 {
        app.push_message(
            MessageKind::System,
            "/remember is only available on the v2 runtime (/runtime set v2); use /approve",
        );
        app.set_status(format!("approval required  {}", app.session_id));
        return Ok(true);
    }
    let remembers = request
        .hint
        .as_deref()
        .map(|hint| hint.contains("/remember"))
        .unwrap_or(false);
    if !remembers {
        app.push_message(
            MessageKind::System,
            "this approval cannot be remembered; use /approve or /deny",
        );
        app.set_status(format!("approval required  {}", app.session_id));
        return Ok(true);
    }
    handle.send_sandbox_approval_decision(
        &app.session_id,
        &request.approval_id,
        request.command_hash.as_deref(),
        "remember",
    )?;
    app.push_message(
        MessageKind::Tool,
        format!(
            "approval sent and remembered for this session\napproval_id: {}",
            request.approval_id
        ),
    );
    app.set_status(format!("approval sent  {}", app.session_id));
    Ok(true)
}

pub(super) fn deny_sandbox_command(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
) -> Result<bool> {
    if let Some(pending) = app.pending_v2_input.clone() {
        // 人工核对时 /deny = 标记失败；其余问题 /deny = 取消。
        return answer_v2_input_with_decision(
            app,
            backend,
            &pending,
            &["mark_failed", "cancel", "deny"],
        );
    }
    let Some(request) = app.pending_sandbox_approval.clone() else {
        app.push_message(
            crate::app::MessageKind::System,
            "no pending sandbox approval",
        );
        app.set_status(format!("ready  {}", app.session_id));
        return Ok(true);
    };

    let Some(handle) = backend.as_ref() else {
        app.deny_pending_sandbox_approval();
        return Ok(true);
    };

    handle.send_sandbox_approval_decision(
        &app.session_id,
        &request.approval_id,
        request.command_hash.as_deref(),
        "deny",
    )?;
    app.push_message(
        crate::app::MessageKind::Tool,
        format!("sandbox denial sent\napproval_id: {}", request.approval_id),
    );
    app.set_status(format!("denial sent  {}", app.session_id));
    Ok(true)
}
