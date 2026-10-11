use ratatui::style::{Color, Modifier, Style};
use ratatui::text::Line;

use crate::app::MessageKind;
use crate::markdown::render_inline;

use super::assistant::render_assistant_body;
use super::common::{
    assistant_title_style, finish_lines, indent_message_line, process_title_style,
    render_labeled_message, system_title_style, tool_title_style, user_title_style,
};

pub(crate) fn format_message(
    kind: MessageKind,
    text: &str,
    trailing_blank: bool,
) -> Vec<Line<'static>> {
    let lines = render_message_block(kind, text);
    finish_lines(lines, trailing_blank)
}

pub(crate) fn format_message_continuation(
    kind: MessageKind,
    text: &str,
    trailing_blank: bool,
) -> Vec<Line<'static>> {
    let lines = render_message_body(kind, text)
        .into_iter()
        .map(indent_message_line)
        .collect::<Vec<_>>();
    finish_lines(lines, trailing_blank)
}

fn render_message_block(kind: MessageKind, text: &str) -> Vec<Line<'static>> {
    match kind {
        MessageKind::User => {
            render_labeled_message("You", user_title_style(), render_message_body(kind, text))
        }
        MessageKind::Assistant => render_labeled_message(
            "Sage",
            assistant_title_style(),
            render_message_body(kind, text),
        ),
        MessageKind::Process => render_labeled_message(
            "Process",
            process_title_style(),
            render_message_body(kind, text),
        ),
        MessageKind::System => render_labeled_message(
            "Notice",
            system_title_style(),
            render_message_body(kind, text),
        ),
        MessageKind::Tool => {
            render_labeled_message("Tool", tool_title_style(), render_message_body(kind, text))
        }
    }
}

fn render_message_body(kind: MessageKind, text: &str) -> Vec<Line<'static>> {
    match kind {
        MessageKind::User => {
            render_plain_body(text, Style::default().fg(Color::Rgb(232, 237, 233)))
        }
        MessageKind::Assistant => render_assistant_body(text),
        MessageKind::Process => render_plain_body(
            text,
            Style::default()
                .fg(Color::Rgb(138, 146, 141))
                .add_modifier(Modifier::DIM),
        ),
        MessageKind::System => {
            render_plain_body(text, Style::default().fg(Color::Rgb(216, 205, 184)))
        }
        MessageKind::Tool => render_plain_body(
            text,
            Style::default()
                .fg(Color::Rgb(161, 177, 191))
                .add_modifier(Modifier::DIM),
        ),
    }
}

fn render_plain_body(text: &str, body_style: Style) -> Vec<Line<'static>> {
    let mut lines = text
        .lines()
        .map(|line| {
            if line.trim().is_empty() {
                Line::from("")
            } else {
                Line::from(render_inline(line, body_style))
            }
        })
        .collect::<Vec<_>>();
    if lines.is_empty() {
        lines.push(Line::from(""));
    }
    lines
}
