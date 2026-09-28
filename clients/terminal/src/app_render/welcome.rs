use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};

use crate::display_policy::{display_mode_name, DisplayMode};

use super::common::{
    accent_style, card_inner_width, subtle_body_style, truncate_middle,
    with_border_with_inner_width,
};

pub(crate) fn welcome_lines(
    width: u16,
    session_id: &str,
    agent_label: &str,
    agent_mode: &str,
    display_mode: DisplayMode,
    max_loop_count: &str,
    workspace_label: &str,
    sandbox_type: &str,
    goal: Option<(&str, &str)>,
) -> Vec<Line<'static>> {
    let max_inner_width = width.saturating_sub(4) as usize;
    let Some(inner_width) = card_inner_width(width, max_inner_width) else {
        return Vec::new();
    };
    let dim = Style::default()
        .fg(Color::Rgb(138, 143, 145))
        .add_modifier(Modifier::DIM);

    let lines = vec![
        Line::from(vec![
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
            Span::styled("agent mode: ", dim),
            Span::styled(
                agent_mode.to_string(),
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ),
        ]),
        Line::from(vec![
            Span::raw("   "),
            Span::styled("display: ", dim),
            Span::styled(display_mode_name(display_mode), accent_style()),
            Span::raw("   "),
            Span::styled("session: ", dim),
            Span::styled(session_id.to_string(), accent_style()),
        ]),
        Line::from(vec![
            Span::styled("agent: ", dim),
            Span::styled(
                truncate_middle(agent_label, inner_width.saturating_sub(7)),
                accent_style(),
            ),
        ]),
        Line::from(vec![
            Span::styled("workspace: ", dim),
            Span::styled(
                truncate_middle(workspace_label, inner_width.saturating_sub(11)),
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ),
        ]),
        Line::from(vec![
            Span::styled("sandbox: ", dim),
            Span::styled(sandbox_type.to_string(), subtle_body_style()),
        ]),
        Line::from(vec![
            Span::styled("goal: ", dim),
            Span::styled(
                goal.map(|(objective, status)| {
                    format!(
                        "{} ({})",
                        truncate_middle(objective, inner_width.saturating_sub(14)),
                        status
                    )
                })
                .unwrap_or_else(|| "(none)".to_string()),
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ),
        ]),
        Line::from(vec![
            Span::styled("loop limit: ", dim),
            Span::styled(max_loop_count.to_string(), subtle_body_style()),
            Span::raw("   "),
            Span::styled("/new", accent_style()),
            Span::styled(" to reset session", dim),
        ]),
        Line::from(""),
        Line::from(vec![
            Span::styled("start: ", dim),
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
