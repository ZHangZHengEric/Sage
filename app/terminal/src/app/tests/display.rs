use super::super::{App, SubmitAction};
use crate::display_policy::DisplayMode;

#[test]
fn display_command_updates_display_mode() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/display set verbose"),
        SubmitAction::Handled
    ));
    assert_eq!(app.display_mode, DisplayMode::Verbose);
}

#[test]
fn display_show_reports_current_mode() {
    let mut app = App::new();
    app.handle_command("/display set verbose");
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/display show"),
        SubmitAction::Handled
    ));
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("display_mode: verbose"));
}
