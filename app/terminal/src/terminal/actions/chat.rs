use anyhow::Result;

use crate::app::App;
use crate::backend::{BackendHandle, BackendRequest};
use crate::terminal::ensure_backend;
use crate::terminal_support::workspace_root;

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
        workspace: Some(workspace_root()),
        skills: app.selected_skills.clone(),
        model_override: app.selected_model.clone(),
        task,
    };
    let handle = ensure_backend(backend, &request)?;
    handle.send_prompt(&request.task)?;
    Ok(true)
}
