use crate::slash_command::SlashCommandDef;

use super::{
    matching_commands, model::CommandPopupItem, popup_height, popup_query, props_from_matches,
    render::popup_lines, CommandPopupProps,
};

const COMMANDS: [SlashCommandDef; 5] = [
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
        example: "/provider",
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
        usage: "/resume",
        example: "/resume latest",
    },
    SlashCommandDef {
        command: "/sessions",
        description: "Browse sessions",
        usage: "/sessions",
        example: "/sessions",
    },
];

#[test]
fn popup_query_extracts_first_line_slash_prefix() {
    assert_eq!(popup_query("/he"), Some("he"));
    assert_eq!(popup_query("/help extra"), None);
    assert_eq!(popup_query("hello"), None);
}

#[test]
fn matching_commands_prioritizes_exact_then_prefix() {
    let matches = matching_commands(&COMMANDS, Some("provider"));
    assert_eq!(matches[0].command, "/provider");
    assert_eq!(matches[1].command, "/providers");
}

#[test]
fn props_include_window_status_when_matches_overflow_visible_rows() {
    let matches = matching_commands(&COMMANDS, Some(""));
    let props = props_from_matches(&matches, 3).expect("popup props");
    assert_eq!(props.window_status.as_deref(), Some("1-4 of 5"));
}

#[test]
fn popup_height_counts_selected_preview_and_status() {
    let props = CommandPopupProps {
        items: vec![CommandPopupItem {
            command: "/help".to_string(),
            description: "Show help".to_string(),
            preview_lines: vec!["usage: /help".to_string(), "example: /help".to_string()],
            selected: true,
        }],
        window_status: Some("1-1 of 1".to_string()),
    };
    assert_eq!(popup_height(Some(&props)), 5);
}

#[test]
fn popup_lines_render_selected_preview_and_window_status() {
    let props = CommandPopupProps {
        items: vec![CommandPopupItem {
            command: "/help".to_string(),
            description: "Show help".to_string(),
            preview_lines: vec!["usage: /help".to_string()],
            selected: true,
        }],
        window_status: Some("1-1 of 1".to_string()),
    };
    let rendered = popup_lines(&props)
        .into_iter()
        .map(|line| {
            line.spans
                .into_iter()
                .map(|span| span.content.to_string())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("/help"));
    assert!(rendered.contains("usage: /help"));
    assert!(rendered.contains("1-1 of 1"));
}
