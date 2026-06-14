use std::time::{Duration, Instant};

use super::super::{App, SubmitAction};

#[test]
fn submit_input_tracks_last_and_current_task() {
    let mut app = App::new();
    app.input = "explain run control".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::RunTask(_)));
    assert_eq!(
        app.last_submitted_task.as_deref(),
        Some("explain run control")
    );
    assert_eq!(app.current_task.as_deref(), Some("explain run control"));
    assert!(app.busy);
}

#[test]
fn insert_char_normalizes_carriage_return() {
    let mut app = App::new();

    app.insert_char('\r');

    assert_eq!(app.input, "\n");
    assert_eq!(app.input_cursor, app.input.len());
}

#[test]
fn insert_text_normalizes_carriage_returns() {
    let mut app = App::new();

    app.insert_text("one\r\ntwo\rthree");

    assert_eq!(app.input, "one\ntwo\nthree");
    assert_eq!(app.input_cursor, app.input.len());
}

#[test]
fn submit_input_handles_greetings_without_backend_task() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::Handled));
    assert!(!app.busy);
    assert!(app.current_task.is_none());
    assert!(app.last_submitted_task.is_none());

    let rendered = app
        .pending_history_lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("hello"));
    assert!(rendered.contains("我在。直接说任务就行。"));
}

#[test]
fn submit_input_handles_identity_question_without_backend_task() {
    let mut app = App::new();
    app.input = "你是谁？".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::Handled));
    assert!(!app.busy);
    assert!(app.current_task.is_none());

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("当前工作空间"));
}

#[test]
fn submit_input_handles_mixed_greeting_identity_without_backend_task() {
    let mut app = App::new();
    app.input = "hello, 你是谁？".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::Handled));
    assert!(!app.busy);
    assert!(app.current_task.is_none());
    assert!(app.last_submitted_task.is_none());

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("hello, 你是谁？"));
    assert_eq!(rendered.matches("Sage Terminal").count(), 1);
}

#[test]
fn submit_input_does_not_intercept_greeting_with_task_intent() {
    let mut app = App::new();
    app.input = "hello，帮我分析项目".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::RunTask(_)));
    assert!(app.busy);
    assert_eq!(app.current_task.as_deref(), Some("hello，帮我分析项目"));
}

#[test]
fn interrupt_command_and_retry_command_parse_cleanly() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/interrupt"),
        SubmitAction::Interrupt
    ));
    assert!(matches!(
        app.handle_command("/retry"),
        SubmitAction::RetryLastTask
    ));
}

#[test]
fn interrupt_request_preserves_partial_output_and_retry_hint() {
    let mut app = App::new();
    app.begin_task_submission("draft answer".to_string(), true);
    app.request_started_at = Some(Instant::now() - Duration::from_millis(1400));
    app.first_output_latency = Some(Duration::from_millis(280));
    app.append_assistant_chunk("partial answer");

    app.interrupt_request();

    assert!(!app.busy);
    assert!(app.current_task.is_none());
    assert_eq!(app.last_submitted_task.as_deref(), Some("draft answer"));

    let rendered = app
        .pending_history_lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("partial answer"));
    assert!(rendered.contains("interrupted • total 1.4s"));
    assert!(rendered.contains("ttft 280ms"));
    assert!(rendered.contains("partial output preserved • /retry available"));
}

#[test]
fn interrupt_request_without_partial_output_still_offers_retry() {
    let mut app = App::new();
    app.begin_task_submission("draft answer".to_string(), true);
    app.request_started_at = Some(Instant::now() - Duration::from_millis(900));

    app.interrupt_request();

    let rendered = app
        .pending_history_lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("interrupted • total 900ms"));
    assert!(rendered.contains("/retry available"));
    assert!(!rendered.contains("partial output preserved"));
}

#[test]
fn begin_task_submission_resets_request_runtime_state() {
    let mut app = App::new();
    app.first_output_latency = Some(Duration::from_millis(10));
    app.last_request_duration = Some(Duration::from_secs(2));
    app.last_first_output_latency = Some(Duration::from_millis(30));
    app.active_phase = Some("planning".to_string());
    app.tool_step_seq = 5;

    app.begin_task_submission("rerun".to_string(), false);

    assert!(app.busy);
    assert_eq!(app.current_task.as_deref(), Some("rerun"));
    assert!(app.first_output_latency.is_none());
    assert!(app.last_request_duration.is_none());
    assert!(app.last_first_output_latency.is_none());
    assert!(app.active_phase.is_none());
    assert_eq!(app.tool_step_seq, 0);
}
