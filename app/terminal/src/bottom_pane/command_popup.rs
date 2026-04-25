use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use unicode_width::UnicodeWidthStr;

use crate::custom_terminal::Frame;
use crate::slash_command::SlashCommandDef;

const POPUP_BG: Color = Color::Rgb(22, 28, 26);
const POPUP_SELECTED_BG: Color = Color::Rgb(34, 44, 40);
const POPUP_COMMAND: Color = Color::Rgb(174, 220, 121);
const POPUP_TEXT: Color = Color::Rgb(205, 211, 207);
const POPUP_HINT: Color = Color::Rgb(117, 127, 122);
const MAX_POPUP_ROWS: usize = 4;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandMatch {
    pub(crate) command: String,
    pub(crate) description: String,
    pub(crate) preview_lines: Vec<String>,
    pub(crate) autocomplete: String,
    pub(crate) action: PopupAction,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum PopupAction {
    HandleCommand(String),
    ShowProvider(String),
    SetDefaultProvider(String),
    EnableSkill(String),
    DisableSkill(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandPopupProps {
    pub(crate) items: Vec<CommandPopupItem>,
    pub(crate) window_status: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandPopupItem {
    pub(crate) command: String,
    pub(crate) description: String,
    pub(crate) preview_lines: Vec<String>,
    pub(crate) selected: bool,
}

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
        if query.is_empty() {
            prefix.push(CommandMatch {
                command: command.command.to_string(),
                description: command.description.to_string(),
                preview_lines: vec![
                    format!("usage: {}", command.usage),
                    format!("example: {}", command.example),
                ],
                autocomplete: format!("{} ", command.command),
                action: PopupAction::HandleCommand(command.command.to_string()),
            });
            continue;
        }
        if name == query {
            exact.push(CommandMatch {
                command: command.command.to_string(),
                description: command.description.to_string(),
                preview_lines: vec![
                    format!("usage: {}", command.usage),
                    format!("example: {}", command.example),
                ],
                autocomplete: format!("{} ", command.command),
                action: PopupAction::HandleCommand(command.command.to_string()),
            });
        } else if name.starts_with(query) {
            prefix.push(CommandMatch {
                command: command.command.to_string(),
                description: command.description.to_string(),
                preview_lines: vec![
                    format!("usage: {}", command.usage),
                    format!("example: {}", command.example),
                ],
                autocomplete: format!("{} ", command.command),
                action: PopupAction::HandleCommand(command.command.to_string()),
            });
        } else if name.contains(query) {
            contains.push(CommandMatch {
                command: command.command.to_string(),
                description: command.description.to_string(),
                preview_lines: vec![
                    format!("usage: {}", command.usage),
                    format!("example: {}", command.example),
                ],
                autocomplete: format!("{} ", command.command),
                action: PopupAction::HandleCommand(command.command.to_string()),
            });
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
    if matches.is_empty() {
        return None;
    }

    let window = visible_window(matches.len(), selected);
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

pub(crate) fn popup_height(props: Option<&CommandPopupProps>) -> u16 {
    props
        .map(|props| {
            props.items.iter().fold(0_u16, |height, item| {
                height
                    + 1
                    + if item.selected {
                        item.preview_lines.len() as u16
                    } else {
                        0
                    }
            }) + u16::from(props.window_status.is_some())
        })
        .unwrap_or(0)
}

pub(crate) fn render(frame: &mut Frame, area: Rect, props: &CommandPopupProps) {
    if area.height == 0 || props.items.is_empty() {
        return;
    }

    frame.render_widget(Paragraph::new(popup_lines(props)), area);
}

fn popup_lines(props: &CommandPopupProps) -> Vec<Line<'static>> {
    let command_width = props
        .items
        .iter()
        .map(|item| UnicodeWidthStr::width(item.command.as_str()))
        .max()
        .unwrap_or(0)
        .clamp(12, 18);
    let mut lines = props
        .items
        .iter()
        .flat_map(|item| {
            let bg = if item.selected {
                POPUP_SELECTED_BG
            } else {
                POPUP_BG
            };
            let mut lines = vec![Line::from(vec![
                Span::styled(
                    if item.selected { "› " } else { "  " },
                    Style::default().fg(POPUP_HINT).bg(bg),
                ),
                Span::styled(
                    format!("{:<width$}", item.command, width = command_width),
                    Style::default()
                        .fg(POPUP_COMMAND)
                        .bg(bg)
                        .add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    item.description.clone(),
                    Style::default().fg(POPUP_TEXT).bg(bg),
                ),
            ])];
            if item.selected {
                for preview in &item.preview_lines {
                    lines.push(Line::from(vec![
                        Span::styled("  ", Style::default().bg(bg)),
                        Span::styled(preview.clone(), Style::default().fg(POPUP_HINT).bg(bg)),
                    ]));
                }
            }
            lines
        })
        .collect::<Vec<_>>();
    if let Some(status) = &props.window_status {
        lines.push(Line::from(vec![
            Span::styled("  ", Style::default().bg(POPUP_BG)),
            Span::styled(status.clone(), Style::default().fg(POPUP_HINT).bg(POPUP_BG)),
        ]));
    }
    lines
}

fn visible_window(total: usize, selected: usize) -> std::ops::Range<usize> {
    let window_len = total.min(MAX_POPUP_ROWS);
    let selected = selected.min(total.saturating_sub(1));
    let mut start = selected.saturating_sub(window_len.saturating_sub(1));
    if start + window_len > total {
        start = total.saturating_sub(window_len);
    }
    start..start + window_len
}

#[cfg(test)]
mod tests {
    use crate::slash_command::SlashCommandDef;

    use super::{
        matching_commands, popup_height, popup_lines, popup_query, props_from_matches,
        CommandPopupProps,
    };

    const COMMANDS: [SlashCommandDef; 4] = [
        SlashCommandDef {
            command: "/help",
            description: "Show help",
            usage: "/help",
            example: "/help",
        },
        SlashCommandDef {
            command: "/provider",
            description: "Manage providers",
            usage: "/provider",
            example: "/provider help",
        },
        SlashCommandDef {
            command: "/providers",
            description: "List providers",
            usage: "/providers",
            example: "/providers",
        },
        SlashCommandDef {
            command: "/resume",
            description: "Resume session",
            usage: "/resume [session_id]",
            example: "/resume latest",
        },
    ];

    #[test]
    fn popup_query_extracts_first_command_token() {
        assert_eq!(popup_query("/pro"), Some("pro"));
        assert_eq!(popup_query("/provider help"), None);
        assert_eq!(popup_query("/provider "), None);
        assert_eq!(popup_query("plain text"), None);
    }

    #[test]
    fn matching_commands_prioritizes_exact_then_prefix() {
        let matches = matching_commands(&COMMANDS, Some("provider"));
        assert_eq!(matches[0].command, "/provider");
        assert_eq!(matches[1].command, "/providers");
    }

    #[test]
    fn popup_height_tracks_visible_items() {
        let matches = matching_commands(&COMMANDS, Some("pro"));
        let props = props_from_matches(&matches, 0);
        assert_eq!(popup_height(props.as_ref()), 4);
    }

    #[test]
    fn props_from_matches_shows_selected_window_when_list_exceeds_max_rows() {
        let matches = vec![
            super::CommandMatch {
                command: "/help".to_string(),
                description: "Show help".to_string(),
                preview_lines: Vec::new(),
                autocomplete: "/help ".to_string(),
                action: super::PopupAction::HandleCommand("/help".to_string()),
            },
            super::CommandMatch {
                command: "/new".to_string(),
                description: "New session".to_string(),
                preview_lines: Vec::new(),
                autocomplete: "/new ".to_string(),
                action: super::PopupAction::HandleCommand("/new".to_string()),
            },
            super::CommandMatch {
                command: "/clear".to_string(),
                description: "Clear".to_string(),
                preview_lines: Vec::new(),
                autocomplete: "/clear ".to_string(),
                action: super::PopupAction::HandleCommand("/clear".to_string()),
            },
            super::CommandMatch {
                command: "/resume".to_string(),
                description: "Resume".to_string(),
                preview_lines: Vec::new(),
                autocomplete: "/resume ".to_string(),
                action: super::PopupAction::HandleCommand("/resume".to_string()),
            },
            super::CommandMatch {
                command: "/sessions".to_string(),
                description: "Sessions".to_string(),
                preview_lines: Vec::new(),
                autocomplete: "/sessions ".to_string(),
                action: super::PopupAction::HandleCommand("/sessions".to_string()),
            },
        ];

        let props = props_from_matches(&matches, 4).expect("windowed props");
        assert_eq!(props.items.len(), 4);
        assert_eq!(props.items[0].command, "/new");
        assert_eq!(props.items[3].command, "/sessions");
        assert!(props.items[3].selected);
        assert_eq!(props.window_status.as_deref(), Some("2-5 of 5"));
    }

    #[test]
    fn selected_item_renders_marker() {
        let props = CommandPopupProps {
            items: vec![
                super::CommandPopupItem {
                    command: "/help".to_string(),
                    description: "Show help".to_string(),
                    preview_lines: Vec::new(),
                    selected: true,
                },
                super::CommandPopupItem {
                    command: "/resume".to_string(),
                    description: "Resume session".to_string(),
                    preview_lines: Vec::new(),
                    selected: false,
                },
            ],
            window_status: None,
        };
        let first_row = popup_lines(&props)[0]
            .spans
            .iter()
            .map(|span| span.content.as_ref())
            .collect::<String>();
        assert!(first_row.contains("› /help"));
    }

    #[test]
    fn selected_preview_adds_extra_popup_row() {
        let props = CommandPopupProps {
            items: vec![super::CommandPopupItem {
                command: "provider-123".to_string(),
                description: "deepseek  •  deepseek-chat".to_string(),
                preview_lines: vec![
                    "model: deepseek-chat".to_string(),
                    "base: https://api.deepseek.com/v1".to_string(),
                ],
                selected: true,
            }],
            window_status: None,
        };
        assert_eq!(popup_height(Some(&props)), 3);
        let rendered = popup_lines(&props)
            .into_iter()
            .map(|line| {
                line.spans
                    .into_iter()
                    .map(|span| span.content.into_owned())
                    .collect::<Vec<_>>()
                    .join("")
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert!(rendered.contains("model: deepseek-chat"));
        assert!(rendered.contains("base: https://api.deepseek.com/v1"));
    }

    #[test]
    fn popup_height_counts_window_status_line() {
        let props = CommandPopupProps {
            items: vec![super::CommandPopupItem {
                command: "/help".to_string(),
                description: "Show help".to_string(),
                preview_lines: Vec::new(),
                selected: true,
            }],
            window_status: Some("1-1 of 5".to_string()),
        };
        assert_eq!(popup_height(Some(&props)), 2);
    }
}
