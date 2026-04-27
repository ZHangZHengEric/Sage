use serde_json::Value;

pub(crate) struct CliStreamEvent {
    pub(crate) event_type: String,
    pub(crate) role: String,
    pub(crate) content: String,
    pub(crate) tool_calls: Vec<CliToolCall>,
    pub(crate) metadata: Option<CliEventMetadata>,
    pub(crate) tool_name: Option<String>,
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

    Some(CliStreamEvent {
        event_type: object
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        role: object
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        content: object
            .get("content")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        tool_calls,
        metadata,
        tool_name: object
            .get("tool_name")
            .and_then(Value::as_str)
            .map(ToString::to_string),
    })
}
