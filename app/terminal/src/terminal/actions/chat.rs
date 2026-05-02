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
        agent_id: app.selected_agent_id.clone(),
        agent_mode: app.agent_mode.clone(),
        max_loop_count: app.max_loop_count,
        workspace: app.workspace_override_path().map(|path| path.to_path_buf()),
        skills: app.selected_skills.clone(),
        model_override: app.selected_model.clone(),
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
    run_task(app, backend, task)
}
