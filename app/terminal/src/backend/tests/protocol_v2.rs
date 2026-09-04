use crate::app::MessageKind;
use crate::backend::protocol::{parse_backend_line, BackendProtocolState};
use crate::backend::BackendEvent;

const INLINE_QUESTIONNAIRE: &str = include_str!("fixtures/v2_inline_questionnaire.ndjson");

#[test]
fn v2_inline_questionnaire_renders_actual_runtime_result_without_pending_interaction() {
    let mut state = BackendProtocolState::default();
    let mut events = Vec::new();
    for line in INLINE_QUESTIONNAIRE.lines() {
        events.extend(state.parse_line(line));
        if line.contains("Where should I deploy?") {
            assert!(
                state.parse_line(line).is_empty(),
                "duplicate result must not repeat questions"
            );
        }
    }
    let questions: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            BackendEvent::Message(MessageKind::Tool, text) => Some(text.as_str()),
            _ => None,
        })
        .collect();
    assert_eq!(
        questions,
        vec!["Choose target\n- Where should I deploy?\n  - staging\n  - production"]
    );
    assert!(!events
        .iter()
        .any(|event| matches!(event, BackendEvent::InputRequested(_))));
    assert!(matches!(events.last(), Some(BackendEvent::Finished)));
}

#[test]
fn v2_inline_questionnaire_accepts_text_json_and_object_options() {
    let mut state = BackendProtocolState::default();
    let mut visible = String::new();
    for line in INLINE_QUESTIONNAIRE.lines() {
        let mut frame: serde_json::Value = serde_json::from_str(line).unwrap();
        if line.contains("Where should I deploy?") {
            let block = &mut frame["data"]["item"]["data"]["content"][0];
            let mut value = block["value"].clone();
            value["questions"][0]["options"] = serde_json::json!([
                {"label": "预发布", "value": "staging"}, "production"
            ]);
            *block = serde_json::json!({"kind": "text", "text": value.to_string()});
        }
        for event in state.parse_line(&frame.to_string()) {
            if let BackendEvent::Message(MessageKind::Tool, text) = event {
                visible.push_str(&text);
            }
        }
    }
    assert!(visible.contains("[staging] 预发布"));
    assert!(visible.contains("production"));
}

#[test]
fn v2_inline_questionnaire_ignores_failed_private_and_unrelated_results() {
    for variant in ["failed", "private", "other-tool", "unvalidated", "empty"] {
        let mut state = BackendProtocolState::default();
        for line in INLINE_QUESTIONNAIRE.lines() {
            let mut frame: serde_json::Value = serde_json::from_str(line).unwrap();
            if variant == "other-tool" && line.contains("questionnaire_async") {
                frame["data"]["item"]["data"]["tool_name"] = serde_json::json!("other_tool");
            }
            if line.contains("Where should I deploy?") {
                let item = &mut frame["data"]["item"];
                match variant {
                    "failed" => item["data"]["error"] = serde_json::json!({"code":"failed"}),
                    "private" => item["visibility"] = serde_json::json!("private"),
                    "unvalidated" => {
                        item["data"]["content"][0]["value"]["validation_passed"] =
                            serde_json::json!(false)
                    }
                    "empty" => {
                        item["data"]["content"][0]["value"]["questions"] = serde_json::json!([])
                    }
                    _ => {}
                }
            }
            assert!(
                !state
                    .parse_line(&frame.to_string())
                    .iter()
                    .any(|event| { matches!(event, BackendEvent::Message(MessageKind::Tool, _)) }),
                "{variant}"
            );
        }
    }
}

fn native(event_type: &str, item_id: Option<&str>, data: serde_json::Value) -> String {
    serde_json::json!({
        "protocol_version": "sage.runtime/v2",
        "event_schema_version": "1",
        "event_id": "event_1",
        "type": event_type,
        "occurred_at": "2026-09-03T09:05:39.812951Z",
        "durability": "durable",
        "session_id": "session_1",
        "run_id": "run_1",
        "session_sequence": 1,
        "run_sequence": 1,
        "turn_id": null,
        "step_id": null,
        "item_id": item_id,
        "data": data,
    })
    .to_string()
}

#[test]
fn v2_session_frame_hydrates_session_from_the_backend() {
    let events = parse_backend_line(
        r#"{"type":"cli_v2_session","session_id":"session_abc","run_id":"run_1","agent_id":"coder","resumed":true}"#,
    );
    assert!(matches!(
        events.as_slice(),
        [BackendEvent::SessionHydrated(meta)]
            if meta.session_id == "session_abc" && meta.command_mode.as_deref() == Some("resume")
    ));
}

#[test]
fn v2_deltas_stream_assistant_text_and_completed_message_is_not_repeated() {
    let mut state = BackendProtocolState::default();
    let started = state.parse_line(&native(
        "message.started",
        Some("item_a"),
        serde_json::json!({"kind":"item","operation":"started","item":null,"delta":null}),
    ));
    assert!(started.is_empty());

    let delta = state.parse_line(&native(
        "message.delta",
        Some("item_a"),
        serde_json::json!({"kind":"item","operation":"delta","item":null,"delta":"Writing "}),
    ));
    assert!(matches!(
        delta.as_slice(),
        [BackendEvent::LiveChunk(MessageKind::Assistant, chunk)] if chunk == "Writing "
    ));

    let completed = state.parse_line(&native(
        "message.completed",
        Some("item_a"),
        serde_json::json!({
            "kind":"item","operation":"completed",
            "item":{"item_id":"item_a","run_id":"run_1","status":"completed","visibility":"public",
                    "data":{"kind":"message","role":"assistant","content":[{"kind":"text","text":"Writing hello.txt","mime_type":"text/plain"}]}}
        }),
    ));
    assert!(
        completed.is_empty(),
        "streamed items must not be rendered twice"
    );

    // 没有增量的完成态（provider 不流式）用完整文本兜底；用户消息回显被忽略。
    let fallback = state.parse_line(&native(
        "message.completed",
        Some("item_b"),
        serde_json::json!({
            "kind":"item","operation":"completed",
            "item":{"item_id":"item_b","run_id":"run_1","status":"completed","visibility":"public",
                    "data":{"kind":"message","role":"assistant","content":[{"kind":"text","text":"Done.","mime_type":"text/plain"}]}}
        }),
    ));
    assert!(matches!(
        fallback.as_slice(),
        [BackendEvent::Message(MessageKind::Assistant, text)] if text == "Done."
    ));
    let user_echo = state.parse_line(&native(
        "message.completed",
        Some("item_u"),
        serde_json::json!({
            "kind":"item","operation":"completed",
            "item":{"item_id":"item_u","run_id":"run_1","status":"completed","visibility":"public",
                    "data":{"kind":"message","role":"user","content":[{"kind":"text","text":"create hello.txt","mime_type":"text/plain"}]}}
        }),
    ));
    assert!(user_echo.is_empty());
}

#[test]
fn v2_tool_events_map_to_tool_lifecycle() {
    let started = parse_backend_line(&native(
        "tool.call.dispatching",
        None,
        serde_json::json!({"kind":"tool","tool_call_id":"call_1","tool_name":"file_write","state":"dispatching"}),
    ));
    assert!(matches!(
        started.as_slice(),
        [BackendEvent::ToolStarted(name), BackendEvent::Status(status)]
            if name == "file_write" && status == "tool  file_write"
    ));

    let succeeded = parse_backend_line(&native(
        "tool.call.succeeded",
        None,
        serde_json::json!({"kind":"tool","tool_call_id":"call_1","tool_name":"file_write","state":"completed"}),
    ));
    assert!(matches!(
        succeeded.as_slice(),
        [BackendEvent::ToolFinished(name)] if name == "file_write"
    ));

    let failed = parse_backend_line(&native(
        "tool.call.failed",
        None,
        serde_json::json!({"kind":"tool","tool_call_id":"call_2","tool_name":"file_write","state":"failed",
            "error":{"code":"sandbox.protected_path","category":"policy_denied","message":"path '.git/hooks/x' is protected"}}),
    ));
    assert!(matches!(
        failed.as_slice(),
        [BackendEvent::ToolFinished(name), BackendEvent::Message(MessageKind::Tool, text)]
            if name == "file_write" && text.contains("sandbox.protected_path")
    ));
}

#[test]
fn v2_approval_interaction_becomes_a_sandbox_approval_request() {
    let events = parse_backend_line(
        r#"{"type":"cli_v2_interaction","run_id":"run_1","interaction_id":"interaction_1","interaction_type":"approval",
            "allowed_decisions":["approve_once","approve_and_remember","deny","cancel"],
            "payload":{"tool_name":"execute_shell_command","arguments":{"command":"git status"},"side_effect_level":"write",
                       "approval_matcher":{"tool_name":"execute_shell_command","fingerprint":"command:sha256:x","summary":"execute_shell_command: git status"},
                       "approval_scopes":["session"],"persistent_approval_allowed":true,"title":"Approval required"}}"#,
    );
    let [BackendEvent::SandboxApprovalRequested(request)] = events.as_slice() else {
        panic!("expected one approval request");
    };
    assert_eq!(request.approval_id, "interaction_1");
    assert_eq!(
        request.command,
        r#"execute_shell_command {"command":"git status"}"#
    );
    assert_eq!(request.category.as_deref(), Some("write"));
    let hint = request
        .hint
        .clone()
        .expect("hint should list the decisions");
    assert!(hint.contains("/approve once"));
    assert!(hint.contains("/remember (execute_shell_command: git status)"));
    assert!(hint.contains("/deny"));

    let plain = parse_backend_line(
        r#"{"type":"cli_v2_interaction","run_id":"run_1","interaction_id":"interaction_2","interaction_type":"approval",
            "allowed_decisions":["approve_once","deny","cancel"],
            "payload":{"tool_name":"file_write","arguments":{"file_path":"a.txt"},"side_effect_level":"write"}}"#,
    );
    let [BackendEvent::SandboxApprovalRequested(request)] = plain.as_slice() else {
        panic!("expected one approval request");
    };
    assert!(!request
        .hint
        .clone()
        .unwrap_or_default()
        .contains("/remember"));
}

#[test]
fn v2_non_approval_interaction_becomes_an_input_request() {
    let events = parse_backend_line(
        r#"{"type":"cli_v2_interaction","run_id":"run_1","interaction_id":"interaction_q","interaction_type":"user_input",
            "allowed_decisions":["submit","cancel"],
            "payload":{"title":"The agent needs your guidance","prompt":"Which target should I use?",
                       "questions":[{"id":"target","title":"Target","options":[{"value":"staging","label":"Staging"}]}]}}"#,
    );
    let [BackendEvent::InputRequested(request)] = events.as_slice() else {
        panic!("expected one input request");
    };
    assert_eq!(request.interaction_id, "interaction_q");
    assert_eq!(request.interaction_type, "user_input");
    assert_eq!(request.allowed_decisions, vec!["submit", "cancel"]);
    assert!(request.prompt.contains("Which target should I use?"));
    assert!(request.prompt.contains("[staging] Staging"));
}

#[test]
fn v2_interaction_resolved_clears_the_approval_and_result_finishes_the_run() {
    let resolved = parse_backend_line(&native(
        "interaction.resolved",
        None,
        serde_json::json!({"kind":"interaction","interaction_id":"interaction_1","interaction_type":"approval",
            "state":"resolved","allowed_decisions":["approve_once","deny","cancel"],
            "payload":{"tool_name":"file_write","side_effect_level":"write"},"decision":"approve_once","revision":1}),
    ));
    assert!(matches!(
        resolved.as_slice(),
        [BackendEvent::SandboxApprovalResolved(resolution)]
            if resolution.approval_id == "interaction_1"
                && resolution.status == "approved"
                && resolution.decision.as_deref() == Some("approve_once")
    ));

    let completed = parse_backend_line(
        r#"{"type":"cli_v2_result","run_id":"run_1","session_id":"session_1","state":"completed","interrupted":false,"final_text":"Done.","error":null}"#,
    );
    assert!(matches!(completed.as_slice(), [BackendEvent::Finished]));

    let failed = parse_backend_line(
        r#"{"type":"cli_v2_result","run_id":"run_1","session_id":"session_1","state":"failed","interrupted":false,"final_text":"",
            "error":{"code":"model.unavailable","message":"provider is down"}}"#,
    );
    assert!(matches!(
        failed.as_slice(),
        [BackendEvent::Error(message), BackendEvent::Finished] if message == "model.unavailable: provider is down"
    ));
}

#[test]
fn v2_notices_and_remembered_approvals_show_in_the_transcript() {
    let notice =
        parse_backend_line(r#"{"type":"cli_v2_notice","content":"session_id: session_1"}"#);
    assert!(matches!(
        notice.as_slice(),
        [BackendEvent::Message(MessageKind::Process, text)] if text == "session_id: session_1"
    ));

    let remembered = parse_backend_line(&native(
        "policy.approval.remembered",
        None,
        serde_json::json!({"kind":"policy","decision_id":"decision_1","decision":"approve_and_remember","policy_version":"1",
            "reason":"file_write: hello.txt","remembered_by":"user","remembered_scope":"session"}),
    ));
    assert!(matches!(
        remembered.as_slice(),
        [BackendEvent::Message(MessageKind::Tool, text)] if text == "approval remembered for this session: file_write: hello.txt"
    ));

    let auto = parse_backend_line(&native(
        "policy.decision.recorded",
        None,
        serde_json::json!({"kind":"policy","decision_id":"decision_2","decision":"allow","policy_version":"1",
            "reason":"approved earlier in this session by user: file_write: hello.txt","remembered_by":"user","remembered_scope":"session"}),
    ));
    assert!(matches!(
        auto.as_slice(),
        [BackendEvent::Message(MessageKind::Tool, text)] if text.starts_with("auto-approved (session)")
    ));

    let plain_decision = parse_backend_line(&native(
        "policy.decision.recorded",
        None,
        serde_json::json!({"kind":"policy","decision_id":"decision_3","decision":"require_interaction","policy_version":"1","reason":"needs approval"}),
    ));
    assert!(plain_decision.is_empty());
}

#[test]
fn v2_steer_frames_report_acceptance_and_rejection() {
    let accepted = parse_backend_line(
        r#"{"type":"cli_v2_steer","run_id":"run_1","status":"accepted","text":"also update the tests","detail":null}"#,
    );
    assert!(matches!(
        accepted.as_slice(),
        [BackendEvent::Message(MessageKind::Process, text)] if text == "steer accepted: also update the tests"
    ));

    let rejected = parse_backend_line(
        r#"{"type":"cli_v2_steer","run_id":"run_1","status":"rejected","text":"too late","detail":"run is already completed"}"#,
    );
    assert!(matches!(
        rejected.as_slice(),
        [BackendEvent::Message(MessageKind::Process, text)] if text == "steer rejected (run is already completed): too late"
    ));
}

#[test]
fn v1_lines_are_still_parsed_by_the_legacy_protocol() {
    let events = parse_backend_line(r#"{"type":"cli_notice","content":"legacy notice"}"#);
    assert!(matches!(
        events.as_slice(),
        [BackendEvent::Message(MessageKind::Process, text)] if text == "legacy notice"
    ));
}

/// 回放真实 `sage v2 run --json` 输出（冒烟抓样，路径已脱敏）：
/// 流式文本必须与完成态 assistant 文本逐字一致，工具/审批/结束事件按真实顺序出现。
fn replay(fixture: &str) -> (Vec<BackendEvent>, String) {
    let mut state = BackendProtocolState::default();
    let mut events = Vec::new();
    let mut expected_text = String::new();
    for line in fixture.lines().filter(|line| !line.trim().is_empty()) {
        let value: serde_json::Value = serde_json::from_str(line).expect("fixture line is JSON");
        if value["type"] == "message.completed"
            && value["data"]["item"]["data"]["role"] == "assistant"
        {
            for block in value["data"]["item"]["data"]["content"].as_array().unwrap() {
                if block["kind"] == "text" {
                    expected_text.push_str(block["text"].as_str().unwrap());
                }
            }
        }
        events.extend(state.parse_line(line));
    }
    (events, expected_text)
}

fn streamed_assistant_text(events: &[BackendEvent]) -> String {
    events
        .iter()
        .filter_map(|event| match event {
            BackendEvent::LiveChunk(MessageKind::Assistant, chunk)
            | BackendEvent::Message(MessageKind::Assistant, chunk) => Some(chunk.as_str()),
            _ => None,
        })
        .collect()
}

#[test]
fn real_protected_path_run_replays_into_tool_failure_and_success() {
    let (events, expected_text) = replay(include_str!("fixtures/v2_protected_path_run.ndjson"));

    assert!(matches!(
        events.first(),
        Some(BackendEvent::SessionHydrated(meta)) if meta.session_id.starts_with("session_")
    ));
    assert!(!expected_text.is_empty());
    assert_eq!(streamed_assistant_text(&events), expected_text);

    let started = events
        .iter()
        .filter(|event| matches!(event, BackendEvent::ToolStarted(_)))
        .count();
    let finished = events
        .iter()
        .filter(|event| matches!(event, BackendEvent::ToolFinished(_)))
        .count();
    assert_eq!(started, finished);
    assert!(
        started >= 2,
        "expected the two file_write calls plus turn_status"
    );
    assert!(events.iter().any(|event| matches!(
        event,
        BackendEvent::Message(MessageKind::Tool, text)
            if text.starts_with("file_write failed: sandbox.protected_path")
    )));
    assert!(!events
        .iter()
        .any(|event| matches!(event, BackendEvent::SandboxApprovalRequested(_))));
    assert!(!events
        .iter()
        .any(|event| matches!(event, BackendEvent::Error(_))));
    assert!(matches!(events.last(), Some(BackendEvent::Finished)));
}

#[test]
fn real_always_ask_run_replays_approval_requests_and_denials() {
    let (events, expected_text) = replay(include_str!("fixtures/v2_always_ask_run.ndjson"));

    assert_eq!(streamed_assistant_text(&events), expected_text);
    let requests = events
        .iter()
        .filter_map(|event| match event {
            BackendEvent::SandboxApprovalRequested(request) => Some(request),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(requests.len(), 2);
    assert!(requests[0].command.starts_with("list_dir "));
    assert_eq!(requests[0].category.as_deref(), Some("read"));
    assert!(requests[0].approval_id.starts_with("interaction_"));
    assert!(!requests[0]
        .hint
        .clone()
        .unwrap_or_default()
        .contains("/remember"));

    let resolutions = events
        .iter()
        .filter_map(|event| match event {
            BackendEvent::SandboxApprovalResolved(resolution) => Some(resolution),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(resolutions.len(), 2);
    assert_eq!(resolutions[0].approval_id, requests[0].approval_id);
    assert_eq!(resolutions[0].status, "denied");
    assert_eq!(resolutions[0].decision.as_deref(), Some("deny"));
    // 审批请求先于其决议，决议先于该工具的 cancelled 结束。
    let request_at = events
        .iter()
        .position(|event| matches!(event, BackendEvent::SandboxApprovalRequested(_)))
        .unwrap();
    let resolved_at = events
        .iter()
        .position(|event| matches!(event, BackendEvent::SandboxApprovalResolved(_)))
        .unwrap();
    let finished_at = events
        .iter()
        .position(|event| matches!(event, BackendEvent::ToolFinished(name) if name == "list_dir"))
        .unwrap();
    assert!(request_at < resolved_at && resolved_at < finished_at);
    assert!(matches!(events.last(), Some(BackendEvent::Finished)));
}
