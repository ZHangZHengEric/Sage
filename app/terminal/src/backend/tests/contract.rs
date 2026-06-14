use serde_json::json;

use crate::backend::contract::{expect_array_field, parse_stream_event, CliJsonCommand};
use crate::backend::protocol::{parse_backend_line, BackendProtocolState};
use crate::backend::BackendEvent;

#[test]
fn parse_stream_event_collects_tool_fields_from_multiple_locations() {
    let event = parse_stream_event(
        r#"{
            "type":"tool_call",
            "tool_calls":[{"function":{"name":"write_file"}}],
            "metadata":{"tool_name":"shell"},
            "tool_name":"exec"
        }"#,
    )
    .expect("stream event should parse");

    let parsed = parse_backend_line(
        r#"{
            "type":"tool_call",
            "tool_calls":[{"function":{"name":"write_file"}}],
            "metadata":{"tool_name":"shell"},
            "tool_name":"exec",
            "content":"running tools"
        }"#,
    );

    assert_eq!(event.event_type, "tool_call");
    let statuses = parsed
        .into_iter()
        .filter_map(|event| match event {
            BackendEvent::Status(status) => Some(status),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec!["tool  exec", "tool  shell", "tool  write_file"]
    );
}

#[test]
fn parse_backend_line_turns_cli_stats_into_stats_then_finished() {
    let events = parse_backend_line(
        r#"{
            "type":"cli_stats",
            "elapsed_seconds":1.25,
            "first_output_seconds":0.18,
            "prompt_tokens":10,
            "completion_tokens":20,
            "total_tokens":30,
            "tool_steps":[{"step":1,"tool_name":"read_file","tool_call_id":"call_1","status":"completed","duration_ms":120.0}],
            "phase_timings":[{"phase":"tool","duration_ms":120.0,"segment_count":1}]
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::Stats(stats))
            if stats.elapsed_seconds == Some(1.25)
                && stats.first_output_seconds == Some(0.18)
                && stats.total_tokens == Some(30)
                && stats.tool_steps.len() == 1
                && stats.tool_steps[0].tool_name == "read_file"
                && stats.phase_timings.len() == 1
                && stats.phase_timings[0].phase == "tool"
    ));
    assert!(matches!(events.get(1), Some(BackendEvent::Finished)));
}

#[test]
fn parse_backend_line_turns_cli_phase_into_phase_event() {
    let events = parse_backend_line(r#"{"type":"cli_phase","phase":"planning"}"#);

    assert!(matches!(
        events.first(),
        Some(BackendEvent::PhaseChanged(phase)) if phase == "planning"
    ));
}

#[test]
fn parse_backend_line_turns_cli_tool_into_tool_events() {
    let started = parse_backend_line(
        r#"{"type":"cli_tool","action":"started","tool_name":"read_file","tool_call_id":"call_1","status":"running"}"#,
    );
    let finished = parse_backend_line(
        r#"{"type":"cli_tool","action":"finished","tool_name":"read_file","tool_call_id":"call_1","status":"completed"}"#,
    );

    assert!(matches!(
        started.first(),
        Some(BackendEvent::ToolStarted(name)) if name == "read_file"
    ));
    assert!(matches!(
        finished.first(),
        Some(BackendEvent::ToolFinished(name)) if name == "read_file"
    ));
}

#[test]
fn protocol_state_converts_cumulative_assistant_content_to_delta() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello!"}"#,
    );
    let duplicate = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello!"}"#,
    );
    let cumulative = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello! World"}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hello!"
    ));
    assert!(duplicate.is_empty());
    assert!(matches!(
        cumulative.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == " World"
    ));
}

#[test]
fn protocol_state_converts_cumulative_content_across_message_ids_to_delta() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello! This is the first answer."}"#,
    );
    let cumulative = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-2","content":"Hello! This is the first answer. More text."}"#,
    );
    let duplicate = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-3","content":"Hello! This is the first answer. More text."}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hello! This is the first answer."
    ));
    assert!(matches!(
        cumulative.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == " More text."
    ));
    assert!(duplicate.is_empty());
}

#[test]
fn protocol_state_converts_short_cumulative_content_across_message_ids_to_delta() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hi!"}"#,
    );
    let cumulative = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-2","content":"Hi! Ready."}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hi!"
    ));
    assert!(matches!(
        cumulative.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == " Ready."
    ));
}

#[test]
fn protocol_state_keeps_plain_delta_streams_unchanged() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hel"}"#,
    );
    let second = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"lo"}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hel"
    ));
    assert!(matches!(
        second.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "lo"
    ));
}

#[test]
fn protocol_state_removes_overlapping_delta_for_same_message_id() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello, Sage is ready"}"#,
    );
    let overlap = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"ready for coding."}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hello, Sage is ready"
    ));
    assert!(matches!(
        overlap.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == " for coding."
    ));
}

#[test]
fn protocol_state_removes_overlapping_delta_across_message_ids() {
    let mut state = BackendProtocolState::default();

    let first = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"当然能。当前项目就是 Rust"}"#,
    );
    let overlap = state.parse_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-2","content":"就是 Rust，可以继续改。"}"#,
    );

    assert!(matches!(
        first.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "当然能。当前项目就是 Rust"
    ));
    assert!(matches!(
        overlap.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "，可以继续改。"
    ));
}

#[test]
fn parse_backend_line_hides_internal_reasoning_events() {
    let events = parse_backend_line(
        r#"{"type":"task_analysis","role":"assistant","content":"internal analysis"}"#,
    );

    assert!(events.is_empty());
}

#[test]
fn parse_backend_line_strips_internal_loop_self_check_text() {
    let events = parse_backend_line(
        r#"{"type":"do_subtask_result","role":"assistant","message_id":"msg-1","content":"Hello. Self-check: Repeating execution loop detected (period=3, cycles=8). Starting now, do not reuse the same path; you must change strategy: try different tools or parameters first; if still blocked, state the blocker clearly and ask one minimal clarification question. Done."}"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "Hello.  Done."
    ));
}

#[test]
fn parse_backend_line_hides_internal_tool_messages_and_statuses() {
    let events = parse_backend_line(
        r#"{
            "type":"tool_call",
            "tool_calls":[{"function":{"name":"search_memory"}}],
            "content":"running memory lookup"
        }"#,
    );

    assert!(events.is_empty());
}

#[test]
fn parse_stream_contract_fixture_round_trip_sequence() {
    let fixture =
        include_str!("../../../../../tests/app/cli/fixtures/stream_contract_round_trip.jsonl");
    let mut saw_phase = false;
    let mut saw_tool_started = false;
    let mut saw_tool_finished = false;
    let mut saw_assistant = false;
    let mut saw_stats = false;
    let mut saw_finished = false;

    for line in fixture.lines().filter(|line| !line.trim().is_empty()) {
        for event in parse_backend_line(line) {
            match event {
                BackendEvent::PhaseChanged(phase) if phase == "planning" => saw_phase = true,
                BackendEvent::ToolStarted(name) if name == "read_file" => saw_tool_started = true,
                BackendEvent::ToolFinished(name) if name == "read_file" => saw_tool_finished = true,
                BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content)
                    if content.contains("Here is the answer.") =>
                {
                    saw_assistant = true
                }
                BackendEvent::Stats(stats)
                    if stats.total_tokens == Some(30)
                        && stats.phase_timings.len() == 3
                        && stats.tool_steps.len() == 1 =>
                {
                    saw_stats = true
                }
                BackendEvent::Finished => saw_finished = true,
                _ => {}
            }
        }
    }

    assert!(saw_phase);
    assert!(saw_tool_started);
    assert!(saw_tool_finished);
    assert!(saw_assistant);
    assert!(saw_stats);
    assert!(saw_finished);
}

#[test]
fn contract_array_field_reports_shape_errors() {
    let payload = json!({"list": {"not": "an array"}});
    let err = expect_array_field(&payload, "list", "sessions.list").expect_err("should fail");
    assert!(err.to_string().contains("sessions.list contract error"));
}

#[test]
fn contract_builds_provider_verify_args_without_user_id() {
    let mutation = crate::backend::ProviderMutation {
        name: Some("demo".to_string()),
        base_url: Some("https://example.com".to_string()),
        api_key: None,
        model: Some("demo-chat".to_string()),
        is_default: Some(false),
    };

    let args = CliJsonCommand::ProviderVerify {
        mutation: &mutation,
    }
    .args();
    assert_eq!(
        args,
        vec![
            "provider",
            "verify",
            "--json",
            "--name",
            "demo",
            "--base-url",
            "https://example.com",
            "--model",
            "demo-chat",
            "--unset-default",
        ]
    );
}

#[test]
fn contract_builds_agents_list_args() {
    let args = CliJsonCommand::AgentsList {
        user_id: "terminal-user",
    }
    .args();

    assert_eq!(args, vec!["agents", "--json", "--user-id", "terminal-user"]);
}
