#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum DisplayMode {
    Compact,
    Verbose,
}

pub(crate) fn display_mode_name(mode: DisplayMode) -> &'static str {
    match mode {
        DisplayMode::Compact => "compact",
        DisplayMode::Verbose => "verbose",
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ToolDisplayClass {
    UserFacing,
    Internal,
    Hidden,
}

pub(crate) fn classify_tool_name(name: &str) -> ToolDisplayClass {
    match name.trim() {
        "" => ToolDisplayClass::Hidden,
        "search_memory" | "turn_status" => ToolDisplayClass::Internal,
        _ => ToolDisplayClass::UserFacing,
    }
}

pub(crate) fn is_visible_tool(mode: DisplayMode, name: &str) -> bool {
    match (mode, classify_tool_name(name)) {
        (_, ToolDisplayClass::Hidden) => false,
        (DisplayMode::Compact, ToolDisplayClass::Internal) => false,
        _ => true,
    }
}

pub(crate) fn visible_tool_names(mode: DisplayMode, names: &[String]) -> Vec<String> {
    let mut visible = names
        .iter()
        .filter(|name| is_visible_tool(mode, name))
        .cloned()
        .collect::<Vec<_>>();
    visible.sort();
    visible.dedup();
    visible
}

pub(crate) fn internal_tool_count(names: &[String]) -> usize {
    names
        .iter()
        .filter(|name| matches!(classify_tool_name(name), ToolDisplayClass::Internal))
        .count()
}

pub(crate) fn display_phase_label(mode: DisplayMode, phase: &str) -> String {
    let normalized = phase.trim();
    if normalized.is_empty() {
        return String::new();
    }

    if matches!(mode, DisplayMode::Verbose) {
        return normalized.replace('_', " ");
    }

    match normalized {
        "assistant_text" | "SimpleAgent" => "response".to_string(),
        "tool" | "ToolSuggestionAgent" => "planning".to_string(),
        "MemoryRecallAgent" => "memory".to_string(),
        other => other.replace('_', " "),
    }
}
