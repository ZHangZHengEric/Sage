use super::super::App;
use crate::backend::{BackendPhaseTiming, BackendStats, BackendToolStep};
use crate::display_policy::DisplayMode;

#[test]
fn compact_completion_summary_matches_golden_fixture() {
    let mut app = App::new();
    app.display_mode = DisplayMode::Compact;
    app.busy = true;
    app.apply_backend_stats(sample_backend_stats());
    app.complete_request();

    assert_eq!(
        render_pending_history(&app),
        include_str!("fixtures/compact_completion.txt").trim_end()
    );
}

#[test]
fn verbose_completion_summary_matches_golden_fixture() {
    let mut app = App::new();
    app.display_mode = DisplayMode::Verbose;
    app.busy = true;
    app.apply_backend_stats(sample_backend_stats());
    app.complete_request();

    assert_eq!(
        render_pending_history(&app),
        include_str!("fixtures/verbose_completion.txt").trim_end()
    );
}

fn render_pending_history(app: &App) -> String {
    app.pending_history_lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n")
        .trim_end()
        .to_string()
}

fn sample_backend_stats() -> BackendStats {
    BackendStats {
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
    }
}
