use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use unicode_width::UnicodeWidthStr;

use crate::custom_terminal::Frame;

use super::model::CommandPopupProps;

const POPUP_BG: Color = Color::Rgb(22, 28, 26);
const POPUP_SELECTED_BG: Color = Color::Rgb(34, 44, 40);
const POPUP_COMMAND: Color = Color::Rgb(174, 220, 121);
const POPUP_TEXT: Color = Color::Rgb(205, 211, 207);
const POPUP_HINT: Color = Color::Rgb(117, 127, 122);
const POPUP_DIVIDER: Color = Color::Rgb(88, 97, 92);

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
            }) + if props.window_status.is_some() { 2 } else { 0 }
        })
        .unwrap_or(0)
}

pub(crate) fn render(frame: &mut Frame, area: Rect, props: &CommandPopupProps) {
    if area.height == 0 || props.items.is_empty() {
        return;
    }

    frame.render_widget(Paragraph::new(popup_lines(props)), area);
}

pub(super) fn popup_lines(props: &CommandPopupProps) -> Vec<Line<'static>> {
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
                        Span::styled("  │ ", Style::default().fg(POPUP_HINT).bg(bg)),
                        Span::styled(preview.clone(), Style::default().fg(POPUP_HINT).bg(bg)),
                    ]));
                }
            }
            lines
        })
        .collect::<Vec<_>>();
    if let Some(status) = &props.window_status {
        lines.push(Line::from(Span::styled(
            "  ───────────────────────────────",
            Style::default().fg(POPUP_DIVIDER).bg(POPUP_BG),
        )));
        lines.push(Line::from(vec![
            Span::styled("  results ", Style::default().fg(POPUP_HINT).bg(POPUP_BG)),
            Span::styled(status.clone(), Style::default().fg(POPUP_TEXT).bg(POPUP_BG)),
        ]));
    }
    lines
}
