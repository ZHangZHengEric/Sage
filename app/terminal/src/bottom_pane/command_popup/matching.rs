use crate::slash_command::SlashCommandDef;

use super::model::{CommandMatch, CommandPopupItem, CommandPopupProps, PopupAction};

pub(crate) const MAX_POPUP_ROWS: usize = 6;

pub(crate) fn popup_query(input: &str) -> Option<&str> {
    let first_line = input.lines().next().unwrap_or("");
    let stripped = first_line.strip_prefix('/')?;
    if stripped.split_whitespace().count() > 1 || stripped.ends_with(' ') {
        return None;
    }
    Some(stripped)
}

pub(crate) fn matching_commands(
    commands: &'static [SlashCommandDef],
    query: Option<&str>,
) -> Vec<CommandMatch> {
    let Some(query) = query else {
        return Vec::new();
    };

    let mut exact = Vec::new();
    let mut prefix = Vec::new();
    let mut contains = Vec::new();

    for command in commands {
        let name = command.command.trim_start_matches('/');
        let item = CommandMatch {
            command: command.command.to_string(),
            description: command.description.to_string(),
            preview_lines: vec![
                format!("usage: {}", command.usage),
                format!("example: {}", command.example),
            ],
            autocomplete: format!("{} ", command.command),
            action: PopupAction::HandleCommand(command.command.to_string()),
        };

        if query.is_empty() {
            prefix.push(item);
        } else if name == query {
            exact.push(item);
        } else if name.starts_with(query) {
            prefix.push(item);
        } else if name.contains(query) {
            contains.push(item);
        }
    }

    exact.extend(prefix);
    exact.extend(contains);
    exact
}

pub(crate) fn props_from_matches(
    matches: &[CommandMatch],
    selected: usize,
) -> Option<CommandPopupProps> {
    props_from_matches_for_rows(matches, selected, MAX_POPUP_ROWS)
}

pub(crate) fn props_from_matches_for_rows(
    matches: &[CommandMatch],
    selected: usize,
    max_rows: usize,
) -> Option<CommandPopupProps> {
    if matches.is_empty() {
        return None;
    }

    let window = visible_window(matches.len(), selected, max_rows.max(1));
    let window_start = window.start;
    let window_end = window.end;
    let visible_count = window_end.saturating_sub(window_start);
    Some(CommandPopupProps {
        items: matches[window]
            .iter()
            .enumerate()
            .map(|(offset, item)| {
                let idx = window_start + offset;
                CommandPopupItem {
                    command: item.command.to_string(),
                    description: item.description.to_string(),
                    preview_lines: item.preview_lines.clone(),
                    selected: idx == selected,
                }
            })
            .collect(),
        window_status: (matches.len() > visible_count)
            .then(|| format!("{}-{} of {}", window_start + 1, window_end, matches.len())),
    })
}

fn visible_window(total: usize, selected: usize, max_rows: usize) -> std::ops::Range<usize> {
    let window_len = total.min(max_rows.max(1));
    let selected = selected.min(total.saturating_sub(1));
    let mut start = selected.saturating_sub(window_len.saturating_sub(1));
    if start + window_len > total {
        start = total.saturating_sub(window_len);
    }
    start..start + window_len
}
