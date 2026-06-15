use crate::app::{App, SubmitAction};
use crate::display_policy::DisplayMode;
use std::path::PathBuf;

#[test]
fn agent_command_sets_selected_agent_and_requests_restart() {
    let mut app = App::new();
    app.set_agent_config_path("coding".to_string());
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/agent set agent_demo"),
        SubmitAction::Handled
    ));
    assert_eq!(app.selected_agent_id.as_deref(), Some("agent_demo"));
    assert!(app.agent_config_path.is_none());
    assert!(app.take_backend_restart_request());
}

#[test]
fn agent_command_rejects_blank_agent_id() {
    let mut app = App::new();
    let _ = app.take_backend_restart_request();

    app.set_selected_agent_id("   ".to_string());

    assert_eq!(app.selected_agent_id, None);
    assert!(!app.take_backend_restart_request());
}

#[test]
fn agent_config_command_sets_config_and_clears_agent_id() {
    let mut app = App::new();
    app.set_selected_agent_id("agent_demo".to_string());
    app.set_agent_mode_selection("multi".to_string());
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/agent config coding"),
        SubmitAction::Handled
    ));
    assert_eq!(app.selected_agent_id, None);
    assert_eq!(
        app.agent_config_path.as_deref(),
        Some(PathBuf::from("coding").as_path())
    );
    assert_eq!(app.agent_id_status_label(), "(default)");
    assert_eq!(app.agent_mode_status_label(), "config default");
    assert_eq!(app.active_agent_label(), "config coding");
    assert!(app.take_backend_restart_request());
}

#[test]
fn agent_config_command_warns_when_coding_config_has_no_workspace() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/agent config coding"),
        SubmitAction::Handled
    ));
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(rendered.contains("requires a repo workspace"));
    assert!(rendered.contains("/workspace set /path/to/repo"));
}

#[test]
fn agent_config_command_does_not_warn_when_coding_config_has_workspace() {
    let mut app = App::new();
    app.set_workspace_selection("/tmp/demo-workspace".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/agent config coding"),
        SubmitAction::Handled
    ));
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(!rendered.contains("requires a repo workspace"));
}

#[test]
fn agent_config_command_accepts_paths_with_spaces() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/agent config /tmp/My Project/coding agent.json"),
        SubmitAction::Handled
    ));
    assert_eq!(
        app.agent_config_path.as_deref(),
        Some(PathBuf::from("/tmp/My Project/coding agent.json").as_path())
    );
}

#[test]
fn agent_config_command_strips_matching_outer_quotes() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/agent config \"/tmp/My Project/coding agent.json\""),
        SubmitAction::Handled
    ));
    assert_eq!(
        app.agent_config_path.as_deref(),
        Some(PathBuf::from("/tmp/My Project/coding agent.json").as_path())
    );

    assert!(matches!(
        app.handle_command("/agent config '/tmp/Other Project/coding agent.json'"),
        SubmitAction::Handled
    ));
    assert_eq!(
        app.agent_config_path.as_deref(),
        Some(PathBuf::from("/tmp/Other Project/coding agent.json").as_path())
    );
}

#[test]
fn agent_mode_status_uses_config_label_until_explicit_override() {
    let mut app = App::new();
    app.set_agent_config_path("coding".to_string());

    assert_eq!(app.agent_mode_status_label(), "config default");
    assert_eq!(app.max_loop_count_status_label(), "config default");

    app.set_agent_mode_selection("multi".to_string());

    assert_eq!(app.agent_mode_status_label(), "multi");
    assert_eq!(app.max_loop_count_status_label(), "config default");
}

#[test]
fn agent_clear_command_clears_agent_config() {
    let mut app = App::new();
    app.set_agent_config_path("coding".to_string());
    app.set_skill_catalog(vec![(
        "docs".to_string(),
        "Documentation helper".to_string(),
        "builtin".to_string(),
    )]);
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/agent clear"),
        SubmitAction::Handled
    ));
    assert!(app.agent_config_path.is_none());
    assert!(app.skill_catalog.is_none());
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

    assert!(matches!(
        app.handle_command("/mode set fibre"),
        SubmitAction::Handled
    ));
    assert_eq!(app.agent_mode, "fibre");
    assert!(app.take_backend_restart_request());
}

#[test]
fn startup_options_apply_without_emitting_messages() {
    let mut app = App::new();

    app.apply_startup_options(
        Some("agent_demo".to_string()),
        None,
        Some("multi".to_string()),
        Some(DisplayMode::Verbose),
        None,
        Some("local".to_string()),
    );

    assert_eq!(app.selected_agent_id.as_deref(), Some("agent_demo"));
    assert_eq!(app.agent_mode, "multi");
    assert_eq!(app.display_mode, DisplayMode::Verbose);
    assert_eq!(app.workspace_label, "~/.sage");
    assert_eq!(app.sandbox_type.as_deref(), Some("local"));
}

#[test]
fn startup_options_apply_explicit_workspace_override() {
    let mut app = App::new();

    app.apply_startup_options(
        Some("agent_demo".to_string()),
        Some(PathBuf::from("/tmp/coding_config.json")),
        Some("multi".to_string()),
        Some(DisplayMode::Compact),
        Some(PathBuf::from("/tmp/demo-workspace")),
        None,
    );

    assert_eq!(app.selected_agent_id, None);
    assert_eq!(
        app.agent_config_path.as_deref(),
        Some(PathBuf::from("/tmp/coding_config.json").as_path())
    );
    assert_eq!(app.agent_mode, "multi");
    assert_eq!(app.display_mode, DisplayMode::Compact);
    assert_eq!(
        app.workspace_override_path(),
        Some(PathBuf::from("/tmp/demo-workspace").as_path())
    );
    assert_eq!(app.workspace_label, "/tmp/demo-workspace");
}

#[test]
fn startup_options_warn_when_coding_config_has_no_workspace() {
    let mut app = App::new();

    app.apply_startup_options(None, Some(PathBuf::from("coding")), None, None, None, None);

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("requires a repo workspace"));
    assert!(rendered.contains("--workspace /path/to/repo"));
}
