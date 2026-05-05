use serde_json::Value;

use super::optional_f64_field;

pub(crate) struct CliStreamEvent {
    pub(crate) event_type: String,
    pub(crate) command_mode: Option<String>,
    pub(crate) session_state: Option<String>,
    pub(crate) session_id: Option<String>,
    pub(crate) role: String,
    pub(crate) content: String,
    pub(crate) phase: Option<String>,
    pub(crate) action: Option<String>,
    pub(crate) tool_calls: Vec<CliToolCall>,
    pub(crate) metadata: Option<CliEventMetadata>,
    pub(crate) tool_name: Option<String>,
    pub(crate) elapsed_seconds: Option<f64>,
    pub(crate) first_output_seconds: Option<f64>,
    pub(crate) prompt_tokens: Option<u64>,
    pub(crate) completion_tokens: Option<u64>,
    pub(crate) total_tokens: Option<u64>,
    pub(crate) tool_steps: Vec<CliToolStep>,
    pub(crate) phase_timings: Vec<CliPhaseTiming>,
    pub(crate) goal: Option<CliGoal>,
    pub(crate) goal_transition: Option<CliGoalTransition>,
    pub(crate) goal_outcome: Option<CliGoalOutcome>,
}

#[derive(Debug, Clone)]
pub(crate) struct CliGoal {
    pub(crate) objective: String,
    pub(crate) status: String,
}

#[derive(Debug, Clone)]
pub(crate) struct CliGoalTransition {
    pub(crate) transition_type: String,
    pub(crate) objective: Option<String>,
    pub(crate) status: Option<String>,
    pub(crate) previous_objective: Option<String>,
    pub(crate) previous_status: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct CliGoalOutcome {
    pub(crate) action: String,
    pub(crate) objective: Option<String>,
    pub(crate) reason: Option<String>,
}

pub(crate) struct CliToolCall {
    pub(crate) function: CliToolFunction,
}

#[derive(Debug, Default)]
pub(crate) struct CliToolFunction {
    pub(crate) name: String,
}

#[derive(Debug)]
pub(crate) struct CliEventMetadata {
    pub(crate) tool_name: Option<String>,
}

#[derive(Debug)]
pub(crate) struct CliToolStep {
    pub(crate) step: u64,
    pub(crate) tool_name: String,
    pub(crate) tool_call_id: Option<String>,
    pub(crate) status: String,
    pub(crate) started_at: Option<f64>,
    pub(crate) finished_at: Option<f64>,
    pub(crate) duration_ms: Option<f64>,
}

#[derive(Debug)]
pub(crate) struct CliPhaseTiming {
    pub(crate) phase: String,
    pub(crate) started_at: Option<f64>,
    pub(crate) finished_at: Option<f64>,
    pub(crate) duration_ms: Option<f64>,
    pub(crate) segment_count: u64,
}

pub(crate) fn parse_stream_event(line: &str) -> Option<CliStreamEvent> {
    let value = serde_json::from_str::<Value>(line).ok()?;
    let object = value.as_object()?;
    let tool_calls = object
        .get("tool_calls")
        .and_then(Value::as_array)
        .map(|calls| {
            calls
                .iter()
                .map(|call| CliToolCall {
                    function: CliToolFunction {
                        name: call
                            .get("function")
                            .and_then(Value::as_object)
                            .and_then(|function| function.get("name"))
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                    },
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let metadata = object
        .get("metadata")
        .and_then(Value::as_object)
        .map(|metadata| CliEventMetadata {
            tool_name: metadata
                .get("tool_name")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        });
    let tool_steps = object
        .get("tool_steps")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|item| CliToolStep {
                    step: item.get("step").and_then(Value::as_u64).unwrap_or(0),
                    tool_name: item
                        .get("tool_name")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string(),
                    tool_call_id: item
                        .get("tool_call_id")
                        .and_then(Value::as_str)
                        .map(ToString::to_string),
                    status: item
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string(),
                    started_at: item.get("started_at").and_then(Value::as_f64),
                    finished_at: item.get("finished_at").and_then(Value::as_f64),
                    duration_ms: item.get("duration_ms").and_then(Value::as_f64),
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let phase_timings = object
        .get("phase_timings")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|item| CliPhaseTiming {
                    phase: item
                        .get("phase")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string(),
                    started_at: item.get("started_at").and_then(Value::as_f64),
                    finished_at: item.get("finished_at").and_then(Value::as_f64),
                    duration_ms: item.get("duration_ms").and_then(Value::as_f64),
                    segment_count: item
                        .get("segment_count")
                        .and_then(Value::as_u64)
                        .unwrap_or(0),
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Some(CliStreamEvent {
        event_type: object
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        command_mode: object
            .get("command_mode")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        session_state: object
            .get("session_state")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        session_id: object
            .get("session_id")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        role: object
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        content: object
            .get("content")
            .and_then(Value::as_str)
            .or_else(|| object.get("message").and_then(Value::as_str))
            .unwrap_or_default()
            .to_string(),
        phase: object
            .get("phase")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        action: object
            .get("action")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        tool_calls,
        metadata,
        tool_name: object
            .get("tool_name")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        elapsed_seconds: optional_f64_field(&value, "elapsed_seconds"),
        first_output_seconds: optional_f64_field(&value, "first_output_seconds"),
        prompt_tokens: object.get("prompt_tokens").and_then(Value::as_u64),
        completion_tokens: object.get("completion_tokens").and_then(Value::as_u64),
        total_tokens: object.get("total_tokens").and_then(Value::as_u64),
        tool_steps,
        phase_timings,
        goal: object
            .get("goal")
            .and_then(Value::as_object)
            .map(|goal| CliGoal {
                objective: goal
                    .get("objective")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                status: goal
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            }),
        goal_transition: object
            .get("goal_transition")
            .and_then(Value::as_object)
            .map(|transition| CliGoalTransition {
                transition_type: transition
                    .get("type")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                objective: transition
                    .get("objective")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
                status: transition
                    .get("status")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
                previous_objective: transition
                    .get("previous_objective")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
                previous_status: transition
                    .get("previous_status")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
            }),
        goal_outcome: object
            .get("goal_outcome")
            .and_then(Value::as_object)
            .map(|outcome| CliGoalOutcome {
                action: outcome
                    .get("action")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                objective: outcome
                    .get("objective")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
                reason: outcome
                    .get("reason")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
            }),
    })
}
