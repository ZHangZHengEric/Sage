use super::super::{App, SubmitAction};

#[test]
fn workspace_command_sets_override() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/workspace set /tmp/demo-workspace"),
        SubmitAction::Handled
    ));
    assert_eq!(
        app.workspace_override_path()
            .map(|path| path.display().to_string()),
        Some("/tmp/demo-workspace".to_string())
    );
    assert_eq!(app.workspace_label, "/tmp/demo-workspace");
}

#[test]
fn workspace_command_clears_override() {
    let mut app = App::new();
    app.set_workspace_selection("/tmp/demo-workspace".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/workspace clear"),
        SubmitAction::Handled
    ));
    assert!(app.workspace_override_path().is_none());
    assert_eq!(app.workspace_label, "~/.sage");
}

#[test]
fn workspace_show_reports_current_workspace() {
    let mut app = App::new();
    app.set_workspace_selection("/tmp/demo-workspace".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/workspace show"),
        SubmitAction::Handled
    ));
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("workspace: /tmp/demo-workspace"));
}
