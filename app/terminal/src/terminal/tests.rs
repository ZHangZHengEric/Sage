use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::app::{ActiveSurfaceKind, App, MessageKind, SubmitAction};
use crate::terminal_layout::desired_viewport_height;
use crate::terminal_support::parse_provider_mutation;

use super::{handle_key, INLINE_VIEWPORT_IDLE_HEIGHT, INLINE_VIEWPORT_MAX_HEIGHT};

#[test]
fn parse_provider_mutation_rejects_invalid_default_flag() {
    let err = parse_provider_mutation(&[String::from("default=maybe")], false)
        .expect_err("default=maybe should fail");
    assert_eq!(
        err.to_string(),
        "invalid default value `maybe`; use true/false, yes/no, on/off, or 1/0"
    );
}

#[test]
fn parse_provider_mutation_rejects_duplicate_fields() {
    let err = parse_provider_mutation(
        &[String::from("model=alpha"), String::from("model=beta")],
        false,
    )
    .expect_err("duplicate model should fail");
    assert_eq!(
        err.to_string(),
        "duplicate provider field `model`; supply it once"
    );
}

#[test]
fn parse_provider_mutation_rejects_empty_values() {
    let err = parse_provider_mutation(&[String::from("name=")], false)
        .expect_err("empty values should fail");
    assert_eq!(err.to_string(), "provider field `name` cannot be empty");
}

#[test]
fn parse_provider_mutation_reports_missing_create_fields() {
    let err = parse_provider_mutation(
        &[
            String::from("name=demo"),
            String::from("base=https://example.com"),
        ],
        true,
    )
    .expect_err("missing model should fail");
    assert_eq!(
        err.to_string(),
        "provider create requires name=..., model=..., base=...; missing: model"
    );
}

#[test]
fn parse_provider_mutation_accepts_false_default_values() {
    let mutation = parse_provider_mutation(
        &[
            String::from("name=demo"),
            String::from("model=demo-chat"),
            String::from("base=https://example.com"),
            String::from("default=off"),
        ],
        true,
    )
    .expect("valid mutation should parse");
    assert_eq!(mutation.is_default, Some(false));
}

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
    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Transcript));
}
