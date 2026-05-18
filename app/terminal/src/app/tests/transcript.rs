use crate::app_render::render_assistant_body;
use crate::display_policy::DisplayMode;
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
fn process_messages_render_in_transcript() {
    let mut app = App::new();
    app.push_message(MessageKind::Process, "[working] still running (3.0s since last event)");

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Process"));
    assert!(rendered.contains("working"));
    assert!(rendered.contains("still running"));
}

#[test]
fn process_notice_replaces_busy_placeholder_with_visible_transcript_message() {
    let mut app = App::new();
    app.begin_task_submission("abc".to_string(), true);

    let live_before = app
        .rendered_live_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(live_before.contains("working"));

    app.push_message(
        MessageKind::Process,
        "[working] MemoryRecallAgent: 遇到网络连接错误，等待 2 秒后重试 (1/8): Connection error.",
    );

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Process"));
    assert!(rendered.contains("MemoryRecallAgent"));
    assert!(rendered.contains("Connection error."));
}

#[test]
fn process_notice_replaces_live_busy_placeholder() {
    let mut app = App::new();
    app.begin_task_submission("abc".to_string(), true);

    app.set_live_notice(
        MessageKind::Process,
        "[working] MemoryRecallAgent: 遇到网络连接错误，等待 2 秒后重试 (1/8): Connection error.",
    );

    let live = app
        .rendered_live_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(live.contains("MemoryRecallAgent"));
    assert!(live.contains("Connection error."));
    assert!(!live.contains("output is streaming"));
}

#[test]
fn backend_system_notice_replaces_live_busy_placeholder() {
    let mut app = App::new();
    app.begin_task_submission("abc".to_string(), true);

    app.set_live_notice(
        MessageKind::System,
        "backend · ToolSuggestionAgent: 遇到网络连接错误，等待 2 秒后重试 (1/8): Connection error.",
    );

    let live = app
        .rendered_live_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(live.contains("backend"));
    assert!(live.contains("ToolSuggestionAgent"));
    assert!(live.contains("Connection error."));
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
    assert!(rendered.contains("running read_file"));
    assert!(rendered.contains("completed read_file"));
    assert!(!rendered.contains("step 1"));
}

#[test]
fn internal_tool_messages_are_hidden_from_transcript() {
    let mut app = App::new();
    app.request_started_at = Some(Instant::now() - Duration::from_secs(2));
    app.start_tool("search_memory".to_string());
    std::thread::sleep(Duration::from_millis(5));
    app.finish_tool("search_memory".to_string());

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
    assert!(!rendered.contains("search_memory"));
}

#[test]
fn verbose_mode_shows_internal_tool_messages() {
    let mut app = App::new();
    app.display_mode = DisplayMode::Verbose;
    app.request_started_at = Some(Instant::now() - Duration::from_secs(2));
    app.start_tool("search_memory".to_string());
    std::thread::sleep(Duration::from_millis(5));
    app.finish_tool("search_memory".to_string());

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
    assert!(rendered.contains("step 1  running search_memory"));
    assert!(rendered.contains("step 1  completed search_memory"));
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
    assert!(rendered.contains("completed •"));
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
    assert_eq!(rendered.matches("Process").count(), 1);
    assert_eq!(rendered.matches("Tool").count(), 0);
    assert!(rendered.contains("tools"));
    assert!(rendered.contains("read_file 120ms"));
    assert!(rendered.contains("grep 84ms"));
    assert!(!rendered.contains("completed read_file"));
    assert!(rendered.contains("120ms"));
    assert!(rendered.contains("84ms"));
    assert!(rendered.contains("phases • planning 500ms"));
    assert!(rendered.contains("response 400ms • 2 segments"));
}

#[test]
fn completed_request_compacts_large_backend_tool_step_summary() {
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
                tool_name: "search_memory".to_string(),
                tool_call_id: Some("call_1".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.0),
                finished_at: Some(10.02),
                duration_ms: Some(20.0),
            },
            BackendToolStep {
                step: 2,
                tool_name: "turn_status".to_string(),
                tool_call_id: Some("call_2".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.02),
                finished_at: Some(10.62),
                duration_ms: Some(600.0),
            },
            BackendToolStep {
                step: 3,
                tool_name: "search_memory".to_string(),
                tool_call_id: Some("call_3".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.62),
                finished_at: Some(10.64),
                duration_ms: Some(20.0),
            },
            BackendToolStep {
                step: 4,
                tool_name: "turn_status".to_string(),
                tool_call_id: Some("call_4".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.64),
                finished_at: Some(11.24),
                duration_ms: Some(600.0),
            },
            BackendToolStep {
                step: 5,
                tool_name: "execute_shell_command".to_string(),
                tool_call_id: Some("call_5".to_string()),
                status: "completed".to_string(),
                started_at: Some(11.24),
                finished_at: Some(11.30),
                duration_ms: Some(60.0),
            },
        ],
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
    assert_eq!(rendered.matches("Process").count(), 1);
    assert_eq!(rendered.matches("Tool").count(), 0);
    assert!(rendered.contains("tools • execute_shell_command • 60ms • internal tools ×4"));
    assert!(rendered.contains("execute_shell_command"));
    assert!(rendered.contains("internal tools ×4"));
    assert!(!rendered.contains("slowest"));
    assert!(!rendered.contains("step 1  completed search_memory"));
    assert!(!rendered.contains("turn_status ×2"));
}

#[test]
fn completed_request_omits_tool_summary_when_only_internal_tools_ran() {
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
                tool_name: "search_memory".to_string(),
                tool_call_id: Some("call_1".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.0),
                finished_at: Some(10.02),
                duration_ms: Some(20.0),
            },
            BackendToolStep {
                step: 2,
                tool_name: "turn_status".to_string(),
                tool_call_id: Some("call_2".to_string()),
                status: "completed".to_string(),
                started_at: Some(10.02),
                finished_at: Some(10.62),
                duration_ms: Some(600.0),
            },
        ],
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
    assert!(!rendered.contains("tools"));
    assert!(!rendered.contains("search_memory"));
    assert!(!rendered.contains("turn_status"));
}

#[test]
fn completed_request_maps_internal_phase_names_to_user_labels() {
    let mut app = App::new();
    app.busy = true;
    app.apply_backend_stats(BackendStats {
        elapsed_seconds: Some(1.25),
        first_output_seconds: Some(0.18),
        prompt_tokens: Some(10),
        completion_tokens: Some(20),
        total_tokens: Some(30),
        tool_steps: Vec::new(),
        phase_timings: vec![
            BackendPhaseTiming {
                phase: "ToolSuggestionAgent".to_string(),
                started_at: Some(9.8),
                finished_at: Some(10.3),
                duration_ms: Some(500.0),
                segment_count: 1,
            },
            BackendPhaseTiming {
                phase: "MemoryRecallAgent".to_string(),
                started_at: Some(10.3),
                finished_at: Some(10.8),
                duration_ms: Some(500.0),
                segment_count: 1,
            },
            BackendPhaseTiming {
                phase: "SimpleAgent".to_string(),
                started_at: Some(10.8),
                finished_at: Some(11.5),
                duration_ms: Some(700.0),
                segment_count: 1,
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
    assert!(rendered.contains("phases • planning 500ms"));
    assert!(rendered.contains("memory 500ms"));
    assert!(rendered.contains("response 700ms"));
    assert!(!rendered.contains("SimpleAgent"));
    assert!(!rendered.contains("MemoryRecallAgent"));
}

#[test]
fn completed_request_keeps_raw_phase_names_in_verbose_mode() {
    let mut app = App::new();
    app.display_mode = DisplayMode::Verbose;
    app.busy = true;
    app.apply_backend_stats(BackendStats {
        elapsed_seconds: Some(1.25),
        first_output_seconds: Some(0.18),
        prompt_tokens: Some(10),
        completion_tokens: Some(20),
        total_tokens: Some(30),
        tool_steps: Vec::new(),
        phase_timings: vec![BackendPhaseTiming {
            phase: "MemoryRecallAgent".to_string(),
            started_at: Some(10.3),
            finished_at: Some(10.8),
            duration_ms: Some(500.0),
            segment_count: 1,
        }],
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
    assert!(rendered.contains("phase • MemoryRecallAgent 500ms"));
    assert!(!rendered.contains("phase • memory 500ms"));
}

#[test]
fn busy_state_without_live_chunks_does_not_render_default_working_message() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();

    let rendered = app
        .rendered_live_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(rendered.contains("working..."));
    assert!(!rendered.contains("Process"));
}

#[test]
fn busy_state_without_live_chunks_renders_active_phase_hint() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.set_active_phase("planning");

    let rendered = app
        .rendered_live_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(rendered.contains("planning..."));
    assert!(!rendered.contains("Process"));
}
