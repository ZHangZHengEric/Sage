//! `sage v2 chat --json` 的 NDJSON 解析：native `RuntimeEvent` 与 `cli_v2_*` 框架帧。
//!
//! 契约见 `app/terminal/CLI_CONTRACT.md` 末尾的 experimental 一节。这里只做投影，
//! 不改变事件语义：assistant 增量→ `LiveChunk`，工具状态→ `ToolStarted/Finished`，
//! 审批交互→ `SandboxApprovalRequested`（复用现有的审批 UI），其余交互→ `InputRequested`。

use std::collections::{HashMap, HashSet};

use serde_json::{Map, Value};

use crate::app::MessageKind;
use crate::backend::protocol_support::truncate;
use crate::backend::types::{
    BackendEvent, BackendSessionMeta, SandboxApprovalRequest, SandboxApprovalResolution,
    V2InputRequest,
};

pub(crate) const V2_PROTOCOL_VERSION: &str = "sage.runtime/v2";
pub(crate) const V2_DECISION_TYPE: &str = "v2_interaction_decision";
pub(crate) const V2_STEER_TYPE: &str = "v2_steer";

/// 一次 Run 内的流式状态：哪些 item 已经以增量形式输出过。
#[derive(Default)]
pub(crate) struct V2StreamState {
    streamed_items: HashSet<String>,
    streamed_chars: HashMap<String, usize>,
    tool_names: HashMap<(String, String), String>,
    rendered_questionnaires: HashSet<(String, String)>,
}

impl V2StreamState {
    fn reset(&mut self) {
        self.streamed_items.clear();
        self.streamed_chars.clear();
        self.tool_names.clear();
        self.rendered_questionnaires.clear();
    }
}

fn str_field<'a>(object: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

/// 判断一行是否属于 v2 协议；不是则返回 None 交给 v1 解析器。
pub(crate) fn parse_v2_line(line: &str, state: &mut V2StreamState) -> Option<Vec<BackendEvent>> {
    let value = serde_json::from_str::<Value>(line).ok()?;
    let object = value.as_object()?;
    let event_type = str_field(object, "type")?;
    let is_native = str_field(object, "protocol_version") == Some(V2_PROTOCOL_VERSION);
    if !is_native && !event_type.starts_with("cli_v2_") {
        return None;
    }
    Some(if is_native {
        parse_native_event(event_type, object, state)
    } else {
        parse_frame(event_type, object, state)
    })
}

fn parse_frame(
    event_type: &str,
    object: &Map<String, Value>,
    state: &mut V2StreamState,
) -> Vec<BackendEvent> {
    match event_type {
        "cli_v2_session" => {
            state.reset();
            let Some(session_id) = str_field(object, "session_id") else {
                return Vec::new();
            };
            let resumed = object
                .get("resumed")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            vec![BackendEvent::SessionHydrated(BackendSessionMeta {
                session_id: session_id.to_string(),
                command_mode: Some(if resumed { "resume" } else { "chat" }.to_string()),
                session_state: Some(if resumed { "existing" } else { "active" }.to_string()),
                goal: None,
            })]
        }
        "cli_v2_notice" => str_field(object, "content")
            .map(|content| {
                vec![BackendEvent::Message(
                    MessageKind::Process,
                    content.to_string(),
                )]
            })
            .unwrap_or_default(),
        "cli_v2_steer" => {
            let status = str_field(object, "status").unwrap_or("rejected");
            let text = str_field(object, "text").unwrap_or_default();
            let detail = str_field(object, "detail")
                .map(|detail| format!(" ({detail})"))
                .unwrap_or_default();
            vec![BackendEvent::Message(
                MessageKind::Process,
                format!("steer {status}{detail}: {}", truncate(text, 160)),
            )]
        }
        "cli_v2_interaction" => parse_interaction(object),
        "cli_v2_result" => {
            let mut events = Vec::new();
            let run_state = str_field(object, "state").unwrap_or("completed");
            if let Some(error) = object.get("error").and_then(Value::as_object) {
                let code = str_field(error, "code").unwrap_or("run.failed");
                let message = str_field(error, "message").unwrap_or("run failed");
                events.push(BackendEvent::Error(format!("{code}: {message}")));
            } else if run_state == "cancelled" {
                events.push(BackendEvent::Message(
                    MessageKind::System,
                    "run cancelled".to_string(),
                ));
            } else if run_state == "suspended" {
                events.push(BackendEvent::Message(
                    MessageKind::System,
                    "run suspended; resume it with sage v2 resume".to_string(),
                ));
            }
            state.reset();
            events.push(BackendEvent::Finished);
            events
        }
        _ => Vec::new(),
    }
}

fn parse_interaction(object: &Map<String, Value>) -> Vec<BackendEvent> {
    let Some(interaction_id) = str_field(object, "interaction_id") else {
        return Vec::new();
    };
    let interaction_type = str_field(object, "interaction_type").unwrap_or("interaction");
    let allowed = object
        .get("allowed_decisions")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let empty = Map::new();
    let payload = object
        .get("payload")
        .and_then(Value::as_object)
        .unwrap_or(&empty);

    if interaction_type == "approval" {
        let tool_name = str_field(payload, "tool_name").unwrap_or("tool");
        let arguments = payload
            .get("arguments")
            .map(|value| match value {
                Value::String(text) => text.clone(),
                other => other.to_string(),
            })
            .unwrap_or_default();
        let command = if arguments.is_empty() {
            tool_name.to_string()
        } else {
            format!("{tool_name} {arguments}")
        };
        let mut hints = vec!["/approve once".to_string()];
        if allowed
            .iter()
            .any(|decision| decision == "approve_and_remember")
        {
            let scope = str_field(payload, "approval_matcher_summary")
                .map(ToString::to_string)
                .or_else(|| {
                    payload
                        .get("approval_matcher")
                        .and_then(Value::as_object)
                        .and_then(|matcher| str_field(matcher, "summary"))
                        .map(ToString::to_string)
                });
            hints.push(match scope {
                Some(summary) => format!("/remember ({summary})"),
                None => "/remember".to_string(),
            });
        }
        hints.push("/deny".to_string());
        let reason = str_field(payload, "risk_reason")
            .or_else(|| str_field(payload, "diagnostic_risk_reason"))
            .map(ToString::to_string);
        return vec![BackendEvent::SandboxApprovalRequested(
            SandboxApprovalRequest {
                command: truncate(&command, 400),
                approval_id: interaction_id.to_string(),
                command_hash: None,
                category: str_field(payload, "side_effect_level").map(ToString::to_string),
                reason,
                approval_mode: None,
                hint: Some(hints.join(" · ")),
            },
        )];
    }

    let mut lines = Vec::new();
    if let Some(title) = str_field(payload, "title") {
        lines.push(title.to_string());
    }
    if let Some(prompt) = str_field(payload, "prompt") {
        lines.push(prompt.to_string());
    }
    if let Some(error) = payload.get("error").and_then(Value::as_object) {
        let code = str_field(error, "code").unwrap_or("error");
        let message = str_field(error, "message").unwrap_or_default();
        lines.push(format!("error: {code}: {message}"));
    }
    if let Some(questions) = payload.get("questions").and_then(Value::as_array) {
        for question in questions.iter().filter_map(Value::as_object) {
            if let Some(title) = str_field(question, "title").or_else(|| str_field(question, "id"))
            {
                lines.push(format!("- {title}"));
            }
            if let Some(options) = question.get("options").and_then(Value::as_array) {
                for option in options.iter().filter_map(Value::as_object) {
                    let value = str_field(option, "value").unwrap_or_default();
                    let label = str_field(option, "label").unwrap_or(value);
                    lines.push(format!("    [{value}] {label}"));
                }
            }
        }
    }
    vec![BackendEvent::InputRequested(Box::new(V2InputRequest {
        interaction_id: interaction_id.to_string(),
        interaction_type: interaction_type.to_string(),
        prompt: lines.join("\n"),
        allowed_decisions: allowed,
    }))]
}

fn parse_native_event(
    event_type: &str,
    object: &Map<String, Value>,
    state: &mut V2StreamState,
) -> Vec<BackendEvent> {
    let empty = Map::new();
    let data = object
        .get("data")
        .and_then(Value::as_object)
        .unwrap_or(&empty);
    let item_id = str_field(object, "item_id").unwrap_or_default();
    match event_type {
        "item.completed" => {
            parse_completed_tool_item(data, str_field(object, "run_id").unwrap_or_default(), state)
        }
        "message.delta" => {
            // 增量只来自模型输出（assistant）；用户/工具消息不会走 delta。
            let Some(delta) = data.get("delta").and_then(Value::as_str) else {
                return Vec::new();
            };
            if delta.is_empty() {
                return Vec::new();
            }
            state.streamed_items.insert(item_id.to_string());
            *state.streamed_chars.entry(item_id.to_string()).or_insert(0) += delta.len();
            vec![BackendEvent::LiveChunk(
                MessageKind::Assistant,
                delta.to_string(),
            )]
        }
        "message.completed" => {
            let Some(item) = data.get("item").and_then(Value::as_object) else {
                return Vec::new();
            };
            let Some(message) = item.get("data").and_then(Value::as_object) else {
                return Vec::new();
            };
            if str_field(message, "role") != Some("assistant") {
                return Vec::new();
            }
            let completed_id = str_field(item, "item_id").unwrap_or(item_id);
            let streamed = state.streamed_chars.get(completed_id).copied().unwrap_or(0);
            if streamed > 0 {
                // 已经流式输出过，完成态不重复渲染。
                return Vec::new();
            }
            let text = message
                .get("content")
                .and_then(Value::as_array)
                .map(|blocks| {
                    blocks
                        .iter()
                        .filter_map(Value::as_object)
                        .filter(|block| str_field(block, "kind") == Some("text"))
                        .filter_map(|block| block.get("text").and_then(Value::as_str))
                        .collect::<Vec<_>>()
                        .join("")
                })
                .unwrap_or_default();
            if text.trim().is_empty() {
                Vec::new()
            } else {
                vec![BackendEvent::Message(MessageKind::Assistant, text)]
            }
        }
        "tool.call.dispatching" => {
            let Some(tool_name) = str_field(data, "tool_name") else {
                return Vec::new();
            };
            vec![
                BackendEvent::ToolStarted(tool_name.to_string()),
                BackendEvent::Status(format!("tool  {tool_name}")),
            ]
        }
        "tool.call.succeeded" | "tool.call.cancelled" | "tool.call.reconciled" => {
            str_field(data, "tool_name")
                .map(|tool_name| vec![BackendEvent::ToolFinished(tool_name.to_string())])
                .unwrap_or_default()
        }
        "tool.call.failed" | "tool.call.unknown" => {
            let Some(tool_name) = str_field(data, "tool_name") else {
                return Vec::new();
            };
            let mut events = vec![BackendEvent::ToolFinished(tool_name.to_string())];
            if let Some(error) = data.get("error").and_then(Value::as_object) {
                let code = str_field(error, "code").unwrap_or("tool.failed");
                let message = str_field(error, "message").unwrap_or_default();
                let state_label = if event_type == "tool.call.unknown" {
                    "outcome unknown"
                } else {
                    "failed"
                };
                events.push(BackendEvent::Message(
                    MessageKind::Tool,
                    format!(
                        "{tool_name} {state_label}: {code}: {}",
                        truncate(message, 200)
                    ),
                ));
            }
            events
        }
        "tool.call.awaiting_approval" => str_field(data, "tool_name")
            .map(|tool_name| {
                vec![BackendEvent::Status(format!(
                    "approval required  {tool_name}"
                ))]
            })
            .unwrap_or_default(),
        "interaction.resolved" => {
            let Some(interaction_id) = str_field(data, "interaction_id") else {
                return Vec::new();
            };
            if str_field(data, "interaction_type") != Some("approval") {
                return Vec::new();
            }
            let decision = str_field(data, "decision").map(ToString::to_string);
            let payload = data.get("payload").and_then(Value::as_object);
            let command = payload
                .and_then(|payload| str_field(payload, "tool_name").map(ToString::to_string));
            vec![BackendEvent::SandboxApprovalResolved(
                SandboxApprovalResolution {
                    approval_id: interaction_id.to_string(),
                    status: decision
                        .as_deref()
                        .map(|value| match value {
                            "approve_once" | "approve_and_remember" => "approved",
                            "deny" => "denied",
                            "cancel" => "cancelled",
                            _ => "resolved",
                        })
                        .unwrap_or("resolved")
                        .to_string(),
                    decision,
                    command,
                    command_hash: None,
                    category: payload
                        .and_then(|payload| str_field(payload, "side_effect_level"))
                        .map(ToString::to_string),
                },
            )]
        }
        "policy.approval.remembered" => {
            let scope = str_field(data, "remembered_scope").unwrap_or("session");
            let reason = str_field(data, "reason").unwrap_or_default();
            vec![BackendEvent::Message(
                MessageKind::Tool,
                format!("approval remembered for this {scope}: {reason}"),
            )]
        }
        "policy.decision.recorded" => match str_field(data, "remembered_by") {
            Some(_) => vec![BackendEvent::Message(
                MessageKind::Tool,
                format!(
                    "auto-approved ({}): {}",
                    str_field(data, "remembered_scope").unwrap_or("session"),
                    str_field(data, "reason").unwrap_or_default()
                ),
            )],
            None => Vec::new(),
        },
        "run.failed" => {
            let Some(error) = data.get("error").and_then(Value::as_object) else {
                return Vec::new();
            };
            let code = str_field(error, "code").unwrap_or("run.failed");
            let message = str_field(error, "message").unwrap_or("run failed");
            vec![BackendEvent::Error(format!("{code}: {message}"))]
        }
        "run.cancelled" => {
            let reason = str_field(data, "reason")
                .map(|reason| format!(" ({reason})"))
                .unwrap_or_default();
            vec![BackendEvent::Message(
                MessageKind::System,
                format!("run cancelled{reason}"),
            )]
        }
        _ => Vec::new(),
    }
}

fn parse_completed_tool_item(
    data: &Map<String, Value>,
    run_id: &str,
    state: &mut V2StreamState,
) -> Vec<BackendEvent> {
    let Some(item) = data.get("item").and_then(Value::as_object) else {
        return Vec::new();
    };
    if str_field(item, "visibility") != Some("public") {
        return Vec::new();
    }
    let Some(body) = item.get("data").and_then(Value::as_object) else {
        return Vec::new();
    };
    let Some(call_id) = str_field(body, "tool_call_id") else {
        return Vec::new();
    };
    let key = (run_id.to_string(), call_id.to_string());
    if str_field(body, "kind") == Some("tool_call") {
        if let Some(name) = str_field(body, "tool_name") {
            state.tool_names.insert(key, name.to_string());
        }
        return Vec::new();
    }
    if str_field(body, "kind") != Some("tool_result")
        || state.tool_names.get(&key).map(String::as_str) != Some("questionnaire_async")
        || body.get("error").is_some_and(|value| !value.is_null())
        || state.rendered_questionnaires.contains(&key)
    {
        return Vec::new();
    }
    let Some(content) = body.get("content").and_then(Value::as_array) else {
        return Vec::new();
    };
    for block in content {
        let payload = match block.get("kind").and_then(Value::as_str) {
            Some("json") => block.get("value").cloned(),
            Some("text") => block
                .get("text")
                .and_then(Value::as_str)
                .and_then(|text| serde_json::from_str::<Value>(text).ok()),
            _ => None,
        };
        let Some(payload) = payload.as_ref().and_then(Value::as_object) else {
            continue;
        };
        if payload.get("success").and_then(Value::as_bool) != Some(true)
            || payload.get("validation_passed").and_then(Value::as_bool) != Some(true)
            || payload.get("should_end").and_then(Value::as_bool) != Some(true)
        {
            continue;
        }
        let Some(questions) = payload.get("questions").and_then(Value::as_array) else {
            continue;
        };
        if questions.is_empty() {
            continue;
        }
        let mut lines = Vec::new();
        if let Some(title) = str_field(payload, "title") {
            lines.push(title.to_string());
        }
        for question in questions.iter().filter_map(Value::as_object) {
            if let Some(title) =
                str_field(question, "title").or_else(|| str_field(question, "question"))
            {
                lines.push(format!("- {title}"));
            }
            if let Some(options) = question.get("options").and_then(Value::as_array) {
                for option in options {
                    if let Some(text) = option.as_str() {
                        lines.push(format!("  - {text}"));
                    } else if let Some(option) = option.as_object() {
                        let value = str_field(option, "value").unwrap_or_default();
                        let label = str_field(option, "label").unwrap_or(value);
                        lines.push(format!("  - [{value}] {label}"));
                    }
                }
            }
        }
        state.rendered_questionnaires.insert(key);
        // Inline questionnaire: the Run has completed; the composer starts the next turn.
        return vec![BackendEvent::Message(MessageKind::Tool, lines.join("\n"))];
    }
    Vec::new()
}
