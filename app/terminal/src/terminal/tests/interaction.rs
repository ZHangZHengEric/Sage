use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::app::{ActiveSurfaceKind, App, MessageKind, SubmitAction};
use crate::slash_command;

use super::super::{handle_key, INLINE_VIEWPORT_IDLE_HEIGHT, INLINE_VIEWPORT_MAX_HEIGHT};
use crate::terminal_layout::desired_viewport_height;

#[test]
fn help_overlay_consumes_typing_without_mutating_input() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();
    assert!(matches!(app.submit_input(), SubmitAction::Handled));

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Char('x'), KeyModifiers::NONE),
        &mut backend,
    )
    .expect("typing while help is open should not fail");

    assert!(handled);
    assert!(app.help_overlay_props().is_some());
    assert!(app.input.is_empty());
}

#[test]
fn help_overlay_enter_closes_modal() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();
    assert!(matches!(app.submit_input(), SubmitAction::Handled));

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("enter while help is open should not fail");

    assert!(handled);
    assert!(app.help_overlay_props().is_none());
}

#[test]
fn welcome_banner_expands_idle_viewport_height() {
    let app = App::new();

    assert!(
        desired_viewport_height(
            &app,
            120,
            INLINE_VIEWPORT_IDLE_HEIGHT,
            INLINE_VIEWPORT_MAX_HEIGHT
        ) > INLINE_VIEWPORT_IDLE_HEIGHT
    );
}

#[test]
fn esc_quits_when_idle_and_input_is_empty() {
    let mut app = App::new();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.should_quit);
}

#[test]
fn esc_clears_input_before_quitting() {
    let mut app = App::new();
    app.input = "draft".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.input.is_empty());
    assert!(!app.should_quit);
}

#[test]
fn esc_closes_popup_before_quitting() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.input.is_empty());
    assert!(!app.should_quit);
}

#[test]
fn help_popup_submit_escape_and_welcome_flow_stays_consistent() {
    let mut app = App::new();
    let mut backend = None;

    app.input = "/he".to_string();
    app.input_cursor = app.input.len();
    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Popup));

    assert!(app.autocomplete_popup());
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("popup submit should not fail");
    assert!(handled);
    assert!(app.help_overlay_props().is_some());

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("help escape should not fail");
    assert!(handled);
    assert!(app.help_overlay_props().is_none());

    app.input = "hello".to_string();
    app.input_cursor = app.input.len();
    let action = app.submit_input();
    assert!(matches!(action, SubmitAction::RunTask(_)));
    app.materialize_pending_ui(120);
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("hello"));
}

#[test]
fn ctrl_t_opens_transcript_overlay_when_idle() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    let _ = app.take_pending_history_lines();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Char('t'), KeyModifiers::CONTROL),
        &mut backend,
    )
    .expect("ctrl-t should not fail");

    assert!(handled);
    assert_eq!(
        app.active_surface_kind(),
        Some(ActiveSurfaceKind::Transcript)
    );
}

#[test]
fn shift_enter_inserts_newline_without_submitting() {
    let mut app = App::new();
    app.input = "first line".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::SHIFT),
        &mut backend,
    )
    .expect("shift-enter should not fail");

    assert!(handled);
    assert_eq!(app.input, "first line\n");
    assert!(!app.busy);
}

#[test]
fn popup_visible_enter_submits_typed_slash_command_instead_of_selected_popup_item() {
    let mut app = App::new();
    app.input = "/exit".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    assert!(app.popup_props().is_some());
    assert!(slash_command::find("/exit").is_some());

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("enter should submit typed slash command");

    assert!(handled);
    assert!(app.should_quit);
}
