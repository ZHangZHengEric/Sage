use super::super::{ActiveSurfaceKind, App};

#[test]
fn help_surface_takes_priority_over_popup_surface() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();

    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Help));
}

#[test]
fn closing_popup_surface_clears_input_without_quitting() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();

    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Popup));
    assert!(app.close_active_surface());
    assert!(app.input.is_empty());
    assert_eq!(app.active_surface_kind(), None);
    assert!(!app.should_quit);
}
