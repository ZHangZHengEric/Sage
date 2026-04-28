use unicode_width::UnicodeWidthStr;

use crate::app::{SessionPickerEntry, SessionPickerMode};

pub(crate) fn provider_help_text() -> String {
    [
        "provider commands",
        "/providers",
        "/provider help",
        "/provider inspect <id>",
        "/provider verify [key=value...]",
        "/provider default <id>",
        "/provider delete <id>",
        "/provider create name=<name> model=<model> base=<url> [key=<api_key>] [default=true|false]",
        "/provider update <id> name=<name>|model=<model>|base=<url>|key=<api_key>|default=true|false ...",
        "",
        "examples",
        "/provider create name=deepseek model=deepseek-chat base=https://api.deepseek.com/v1",
        "/provider update provider-123 model=deepseek-reasoner",
        "/provider verify model=deepseek-chat base=https://api.deepseek.com/v1",
        "/provider default provider-123",
    ]
    .join("\n")
}

pub(crate) fn session_picker_preview_lines(
    item: &SessionPickerEntry,
    mode: SessionPickerMode,
) -> Vec<String> {
    let mut lines = vec![
        format!("session  {}", item.session_id),
        format!(
            "updated  {}  •  {} msgs",
            item.updated_at, item.message_count
        ),
        format!("title  {}", truncate_right(&item.title, 64)),
    ];
    if let Some(preview) = &item.preview {
        lines.push("recent".to_string());
        lines.extend(preview_excerpt_lines(preview, 2, 54));
    }
    lines.push(match mode {
        SessionPickerMode::Resume => "enter resumes this session".to_string(),
        SessionPickerMode::Browse => "enter opens this session summary".to_string(),
    });
    lines
}

fn preview_excerpt_lines(text: &str, max_lines: usize, max_width: usize) -> Vec<String> {
    let mut out = text
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            (!trimmed.is_empty()).then(|| truncate_right(trimmed, max_width))
        })
        .take(max_lines)
        .collect::<Vec<_>>();
    let total_non_empty = text.lines().filter(|line| !line.trim().is_empty()).count();
    if total_non_empty > out.len() {
        out.push("…".to_string());
    }
    if out.is_empty() {
        out.push("(no preview)".to_string());
    }
    out
}

fn truncate_right(text: &str, max_width: usize) -> String {
    if max_width == 0 || UnicodeWidthStr::width(text) <= max_width {
        return text.to_string();
    }
    if max_width == 1 {
        return "…".to_string();
    }

    let mut out = String::new();
    let mut width = 0usize;
    for ch in text.chars() {
        let ch_width = UnicodeWidthStr::width(ch.encode_utf8(&mut [0; 4]));
        if width + ch_width > max_width.saturating_sub(1) {
            break;
        }
        out.push(ch);
        width += ch_width;
    }
    out.push('…');
    out
}
