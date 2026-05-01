use crate::app::{App, SubmitAction};
use std::path::PathBuf;

#[test]
fn agent_command_sets_selected_agent_and_requests_restart() {
    let mut app = App::new();

    assert!(matches!(app.handle_command("/agent set agent_demo"), SubmitAction::Handled));
    assert_eq!(app.selected_agent_id.as_deref(), Some("agent_demo"));
    assert!(app.take_backend_restart_request());
}

#[test]
fn agent_list_command_returns_list_action() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/agent list"),
        SubmitAction::ListAgents
    ));
}

#[test]
fn mode_command_updates_agent_mode_and_requests_restart() {
    let mut app = App::new();

    assert!(matches!(app.handle_command("/mode set fibre"), SubmitAction::Handled));
    assert_eq!(app.agent_mode, "fibre");
    assert!(app.take_backend_restart_request());
}

#[test]
fn startup_agent_options_apply_without_emitting_messages() {
    let mut app = App::new();

    app.apply_startup_agent_options(
        Some("agent_demo".to_string()),
        Some("multi".to_string()),
        None,
    );

    assert_eq!(app.selected_agent_id.as_deref(), Some("agent_demo"));
    assert_eq!(app.agent_mode, "multi");
    assert_eq!(app.workspace_label, "~/.sage");
}

#[test]
fn startup_agent_options_apply_explicit_workspace_override() {
    let mut app = App::new();

    app.apply_startup_agent_options(
        Some("agent_demo".to_string()),
        Some("multi".to_string()),
        Some(PathBuf::from("/tmp/demo-workspace")),
    );

    assert_eq!(app.selected_agent_id.as_deref(), Some("agent_demo"));
    assert_eq!(app.agent_mode, "multi");
    assert_eq!(app.workspace_override_path(), Some(PathBuf::from("/tmp/demo-workspace").as_path()));
    assert_eq!(app.workspace_label, "/tmp/demo-workspace");
}
