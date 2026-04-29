use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};

use super::common::{
    accent_style, card_inner_width, subtle_body_style, truncate_middle,
    with_border_with_inner_width,
};

const SESSION_HEADER_MAX_INNER_WIDTH: usize = 56;

pub(crate) fn welcome_lines(
    width: u16,
    session_id: &str,
    agent_mode: &str,
    max_loop_count: u32,
    workspace_label: &str,
) -> Vec<Line<'static>> {
    let Some(inner_width) = card_inner_width(width, SESSION_HEADER_MAX_INNER_WIDTH) else {
        return Vec::new();
    };
    let dim = Style::default()
        .fg(Color::Rgb(138, 143, 145))
        .add_modifier(Modifier::DIM);

    let lines = vec![
        Line::from(vec![
            Span::styled(">_ ", dim),
            Span::styled(
                "Sage Terminal",
                Style::default()
                    .fg(Color::Rgb(243, 245, 241))
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw(" "),
            Span::styled(format!("(v{})", env!("CARGO_PKG_VERSION")), dim),
        ]),
        Line::from(""),
        Line::from(vec![
            Span::styled("mode: ", dim),
            Span::styled(
                agent_mode.to_string(),
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ),
            Span::raw("   "),
            Span::styled("session: ", dim),
            Span::styled(session_id.to_string(), accent_style()),
        ]),
        Line::from(vec![
            Span::styled("directory: ", dim),
            Span::styled(
                truncate_middle(workspace_label, inner_width.saturating_sub(11)),
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ),
        ]),
        Line::from(vec![
            Span::styled("loops: ", dim),
            Span::styled(max_loop_count.to_string(), subtle_body_style()),
            Span::raw("   "),
            Span::styled("/new", accent_style()),
            Span::styled(" to reset session", dim),
        ]),
        Line::from(""),
        Line::from(vec![
            Span::styled("next: ", dim),
            Span::styled("/help", accent_style()),
            Span::styled("  ", dim),
            Span::styled("/resume", accent_style()),
            Span::styled("  ", dim),
            Span::styled("/sessions", accent_style()),
            Span::styled("  ", dim),
            Span::styled("/doctor", accent_style()),
        ]),
    ];

    let mut out = with_border_with_inner_width(lines, inner_width);
    out.extend([
        Line::from(vec![
            Span::styled(
                "Tip: ",
                Style::default()
                    .fg(Color::Rgb(243, 245, 241))
                    .add_modifier(Modifier::BOLD),
            ),
            Span::styled("Use ", dim),
            Span::styled("/help", accent_style()),
            Span::styled(
                " to list commands, or start typing below to chat with Sage.",
                dim,
            ),
        ]),
        Line::from(""),
    ]);
    out
}
