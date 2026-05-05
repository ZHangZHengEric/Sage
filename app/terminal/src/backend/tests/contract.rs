use serde_json::json;

use crate::backend::contract::{expect_array_field, parse_stream_event, CliJsonCommand};
use crate::backend::protocol::parse_backend_line;
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
fn parse_backend_line_hydrates_session_goal_from_cli_session() {
    let events = parse_backend_line(
        r#"{
            "type":"cli_session",
            "command_mode":"resume",
            "session_state":"existing",
            "session_id":"session-demo",
            "goal":{"objective":"ship runtime goal contract","status":"active"},
            "goal_transition":{"type":"resumed","objective":"ship runtime goal contract","status":"active"}
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::SessionHydrated(meta))
            if meta.session_id == "session-demo"
                && meta.command_mode.as_deref() == Some("resume")
                && meta.session_state.as_deref() == Some("existing")
                && meta.goal.as_ref().map(|goal| goal.objective.as_str()) == Some("ship runtime goal contract")
                && meta.goal.as_ref().map(|goal| goal.status.as_str()) == Some("active")
                && meta.goal_transition.as_ref().map(|transition| transition.transition_type.as_str()) == Some("resumed")
    ));
}

#[test]
fn parse_backend_line_hydrates_session_goal_from_cli_goal_event() {
    let events = parse_backend_line(
        r#"{
            "type":"cli_goal",
            "command_mode":"run",
            "session_state":"existing",
            "session_id":"session-demo",
            "source":"session_refresh",
            "goal":{"objective":"ship runtime goal contract","status":"active"},
            "goal_transition":{"type":"resumed","objective":"ship runtime goal contract","status":"active"}
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::SessionHydrated(meta))
            if meta.session_id == "session-demo"
                && meta.command_mode.as_deref() == Some("run")
                && meta.session_state.as_deref() == Some("existing")
                && meta.goal.as_ref().map(|goal| goal.objective.as_str()) == Some("ship runtime goal contract")
                && meta.goal_transition.as_ref().map(|transition| transition.transition_type.as_str()) == Some("resumed")
    ));
}

#[test]
fn parse_backend_line_hydrates_session_goal_from_tool_result_goal_update() {
    let events = parse_backend_line(
        r#"{
            "type":"tool_result",
            "session_id":"session-demo",
            "metadata":{"tool_name":"turn_status"},
            "goal":{"objective":"ship runtime goal contract","status":"completed"},
            "goal_transition":{"type":"completed","objective":"ship runtime goal contract","status":"completed"},
            "content":"completed turn_status"
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::SessionHydrated(meta))
            if meta.session_id == "session-demo"
                && meta.goal.as_ref().map(|goal| goal.objective.as_str()) == Some("ship runtime goal contract")
                && meta.goal.as_ref().map(|goal| goal.status.as_str()) == Some("completed")
                && meta.goal_transition.as_ref().map(|transition| transition.transition_type.as_str()) == Some("completed")
    ));
}

#[test]
fn parse_backend_line_hydrates_session_goal_clear_transition_without_goal_payload() {
    let events = parse_backend_line(
        r#"{
            "type":"tool_result",
            "session_id":"session-demo",
            "metadata":{"tool_name":"turn_status"},
            "goal":null,
            "goal_transition":{"type":"cleared","previous_objective":"ship runtime goal contract","previous_status":"active"},
            "content":"completed turn_status"
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::SessionHydrated(meta))
            if meta.session_id == "session-demo"
                && meta.goal.is_none()
                && meta.goal_transition.as_ref().map(|transition| transition.transition_type.as_str()) == Some("cleared")
                && meta.goal_transition.as_ref().and_then(|transition| transition.previous_objective.as_deref()) == Some("ship runtime goal contract")
    ));
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
fn parse_backend_line_turns_cli_notice_into_process_message() {
    let events = parse_backend_line(
        r#"{"type":"cli_notice","level":"info","content":"[working] still running (3.0s since last event)"}"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::Message(crate::app::MessageKind::Process, text))
            if text.contains("[working] still running")
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
fn parse_backend_line_promotes_goal_outcome_to_process_message() {
    let events = parse_backend_line(
        r#"{
            "type":"tool_result",
            "session_id":"session-demo",
            "metadata":{"tool_name":"turn_status"},
            "goal_outcome":{"action":"paused","objective":"wait for approval","reason":"waiting_for_user_input"},
            "content":"completed turn_status"
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::Message(crate::app::MessageKind::Process, text))
            if text.contains("goal paused") && text.contains("wait for approval")
    ));
}

#[test]
fn parse_backend_line_ignores_structured_log_json_without_stream_type() {
    let events = parse_backend_line(
        r#"{
            "level":"ERROR",
            "time":"2026-05-05 02:00:00.000",
            "file":"services/chat_service.py:123",
            "msg":"backend exploded"
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
    let mut saw_goal = false;

    for line in fixture.lines().filter(|line| !line.trim().is_empty()) {
        for event in parse_backend_line(line) {
            match event {
                BackendEvent::SessionHydrated(meta)
                    if meta.session_id == "session-demo"
                        && meta.goal.as_ref().map(|goal| goal.objective.as_str())
                            == Some("Ship the runtime goal contract") =>
                {
                    saw_goal = true
                }
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

    assert!(saw_goal);
    assert!(saw_phase);
    assert!(saw_tool_started);
    assert!(saw_tool_finished);
    assert!(saw_assistant);
    assert!(saw_stats);
    assert!(saw_finished);
}

#[test]
fn parse_backend_line_treats_assistant_text_as_live_assistant_output() {
    let events = parse_backend_line(
        r#"{
            "type":"assistant_text",
            "content":"hello from assistant text"
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::LiveChunk(crate::app::MessageKind::Assistant, content))
            if content == "hello from assistant text"
    ));
}

#[test]
fn parse_backend_line_uses_cli_error_message_field_as_error_content() {
    let events = parse_backend_line(
        r#"{
            "type":"cli_error",
            "message":"session_root_space is required for first initialization"
        }"#,
    );

    assert!(matches!(
        events.first(),
        Some(BackendEvent::Error(message))
            if message == "session_root_space is required for first initialization"
    ));
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
