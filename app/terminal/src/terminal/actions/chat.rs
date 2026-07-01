use anyhow::Result;

use crate::app::App;
use crate::backend::{BackendHandle, BackendRequest};
use crate::terminal::ensure_backend;

pub(super) fn run_task(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    task: String,
) -> Result<bool> {
    let request = BackendRequest {
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
    app.clear_pending_sandbox_approval();
    app.set_status(format!("approval sent  {}", app.session_id));
    Ok(true)
}

pub(super) fn deny_sandbox_command(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
) -> Result<bool> {
    let Some(request) = app.pending_sandbox_approval.clone() else {
        app.push_message(
            crate::app::MessageKind::System,
            "no pending sandbox approval",
        );
        app.set_status(format!("ready  {}", app.session_id));
        return Ok(true);
    };

    if let Some(handle) = backend.as_ref() {
        handle.send_sandbox_approval_decision(
            &app.session_id,
            &request.approval_id,
            request.command_hash.as_deref(),
            "deny",
        )?;
    }
    app.deny_pending_sandbox_approval();
    Ok(true)
}
