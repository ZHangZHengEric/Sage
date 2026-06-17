use super::super::{App, SubmitAction};

#[test]
fn sandbox_command_sets_override_and_requests_restart() {
    let mut app = App::new();
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/sandbox set local"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_type.as_deref(), Some("local"));
    assert!(app.take_backend_restart_request());
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox type set: local"));
}

#[test]
fn sandbox_show_reports_current_override() {
    let mut app = App::new();
    app.set_sandbox_type_selection("remote".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/sandbox show"),
        SubmitAction::Handled
    ));

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox: remote"));
    assert!(!rendered.contains("sandbox_type:"));
}

#[test]
fn sandbox_clear_removes_override() {
    let mut app = App::new();
    app.set_sandbox_type_selection("passthrough".to_string());
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/sandbox clear"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_type, None);
    assert!(app.take_backend_restart_request());
}
