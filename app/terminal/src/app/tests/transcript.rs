use crate::app_render::render_assistant_body;
use std::time::{Duration, Instant};

use super::super::{App, MessageKind};
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};

#[test]
fn transcript_messages_render_with_role_headers() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    app.push_message(MessageKind::Assistant, "world");

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("• "));
    assert!(rendered.contains("You"));
    assert!(rendered.contains("Sage"));
    assert!(rendered.contains("hello"));
    assert!(rendered.contains("world"));
}

#[test]
fn assistant_tables_render_as_grid_lines() {
    let lines = render_assistant_body(
        "| name | value |\n| ---- | ----- |\n| mode | simple |\n| loops | 50 |",
    );
    let rendered = lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("│ name"));
    assert!(rendered.contains("├"));
    assert!(rendered.contains("simple"));
}

#[test]
fn assistant_long_code_blocks_are_folded() {
    let code =
        "```rust\nline1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n```";
    let lines = render_assistant_body(code);
    let rendered = lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("code rust"));
    assert!(rendered.contains("… 2 more lines"));
}

#[test]
fn streamed_multiline_assistant_output_keeps_single_role_header() {
    let mut app = App::new();
    app.append_assistant_chunk("line one\n");
    app.append_assistant_chunk("line two\n");
    app.complete_request();

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
    assert_eq!(rendered.matches("Sage").count(), 1);
    assert!(rendered.contains("line one"));
    assert!(rendered.contains("line two"));
}

#[test]
fn transcript_overlay_opens_after_history_is_committed() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    let _ = app.take_pending_history_lines();
    app.open_transcript_overlay();

    let props = app.transcript_overlay_props(90).expect("transcript props");
    assert!(props.lines.iter().any(|line| {
        line.spans
            .iter()
            .any(|span| span.content.as_ref().contains("hello"))
    }));
}

#[test]
fn transcript_overlay_scrolls_for_long_history() {
    let mut app = App::new();
    for idx in 0..40 {
        app.push_message(MessageKind::Assistant, format!("line {idx}"));
    }
    let _ = app.take_pending_history_lines();
    app.open_transcript_overlay();
    assert!(app.scroll_transcript_overlay_down(5));
    let props = app.transcript_overlay_props(90).expect("transcript props");
    assert!(props.scroll > 0);
}

#[test]
fn tool_messages_include_step_number_and_duration() {
    let mut app = App::new();
    app.request_started_at = Some(Instant::now() - Duration::from_secs(2));
    app.start_tool("read_file".to_string());
    std::thread::sleep(Duration::from_millis(5));
    app.finish_tool("read_file".to_string());

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
    assert!(rendered.contains("step 1  running read_file"));
    assert!(rendered.contains("step 1  completed read_file"));
}

#[test]
fn completed_request_queues_timing_summary_into_transcript() {
    let mut app = App::new();
    app.busy = true;
    app.request_started_at = Some(Instant::now() - Duration::from_millis(1500));
    app.first_output_latency = Some(Duration::from_millis(320));
    app.append_assistant_chunk("done");
    app.complete_request();

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
    assert!(rendered.contains("completed"));
    assert!(rendered.contains("total 1.5s"));
    assert!(rendered.contains("ttft 320ms"));
}

#[test]
fn completed_request_prefers_backend_stats_for_summary() {
    let mut app = App::new();
    app.busy = true;
    app.request_started_at = Some(Instant::now() - Duration::from_secs(9));
    app.first_output_latency = Some(Duration::from_secs(2));
    app.apply_backend_stats(BackendStats {
        elapsed_seconds: Some(1.25),
        first_output_seconds: Some(0.18),
        prompt_tokens: Some(10),
        completion_tokens: Some(20),
        total_tokens: Some(30),
        tool_steps: Vec::new(),
        phase_timings: Vec::new(),
    });
    app.complete_request();

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
    assert!(rendered.contains("total 1.2s"));
    assert!(rendered.contains("ttft 180ms"));
    assert!(rendered.contains("tokens 30"));
    assert!(!rendered.contains("total 9.0s"));
}

#[test]
fn completed_request_renders_backend_tool_step_summary() {
    let mut app = App::new();
    app.busy = true;
    app.apply_backend_stats(BackendStats {
        elapsed_seconds: Some(1.25),
        first_output_seconds: Some(0.18),
        prompt_tokens: Some(10),
        completion_tokens: Some(20),
        total_tokens: Some(30),
        tool_steps: vec![
            BackendToolStep {
                step: 1,
                tool_name: "read_file".to_string(),
                tool_call_id: Some("call_1".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.0),
                finished_at: Some(10.12),
                duration_ms: Some(120.0),
            },
            BackendToolStep {
                step: 2,
                tool_name: "grep".to_string(),
                tool_call_id: Some("call_2".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.2),
                finished_at: Some(10.284),
                duration_ms: Some(84.0),
            },
        ],
        phase_timings: vec![
            BackendPhaseTiming {
                phase: "planning".to_string(),
                started_at: Some(9.8),
                finished_at: Some(10.3),
                duration_ms: Some(500.0),
                segment_count: 1,
            },
            BackendPhaseTiming {
                phase: "assistant_text".to_string(),
                started_at: Some(11.1),
                finished_at: Some(11.5),
                duration_ms: Some(400.0),
                segment_count: 2,
            },
        ],
    });
    app.complete_request();

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
    assert!(rendered.contains("tool steps"));
    assert!(rendered.contains("step 1  completed read_file"));
    assert!(rendered.contains("step 2  completed grep"));
    assert!(rendered.contains("120ms"));
    assert!(rendered.contains("84ms"));
    assert!(rendered.contains("phase timings"));
    assert!(rendered.contains("planning"));
    assert!(rendered.contains("assistant text"));
    assert!(rendered.contains("2 segments"));
}
