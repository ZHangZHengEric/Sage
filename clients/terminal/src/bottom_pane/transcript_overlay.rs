use ratatui::text::{Line, Span};
use ratatui::widgets::{Clear, Paragraph};

use crate::bottom_pane::{
    centered_rect, overlay_background_style, overlay_block, overlay_body_style, overlay_divider,
    overlay_hint_style, overlay_muted_style,
};
use crate::custom_terminal::Frame;
use crate::wrap::wrap_lines;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TranscriptOverlayProps {
    pub(crate) title: String,
    pub(crate) lines: Vec<Line<'static>>,
    pub(crate) scroll: u16,
    pub(crate) footer_hint: String,
    pub(crate) status: String,
}

pub(crate) fn render(frame: &mut Frame, props: &TranscriptOverlayProps) {
    let area = centered_rect(frame.area(), 92, required_height(props));
    frame.render_widget(Clear, area);
    let body = overlay_lines(props, area.width.saturating_sub(2));
    frame.render_widget(
        Paragraph::new(body)
            .scroll((props.scroll, 0))
            .block(overlay_block(props.title.clone()))
            .style(overlay_background_style()),
        area,
    );
}

pub(crate) fn required_height(props: &TranscriptOverlayProps) -> u16 {
    let desired = props.lines.len().min(18) as u16 + 5;
    desired.clamp(10, 22)
}

pub(crate) fn wrapped_line_count(props: &TranscriptOverlayProps, width: u16) -> u16 {
    let body_width = width.saturating_sub(2).max(1);
    overlay_lines(props, body_width)
        .len()
        .min(u16::MAX as usize) as u16
}

fn overlay_lines(props: &TranscriptOverlayProps, width: u16) -> Vec<Line<'static>> {
    let mut lines = if props.lines.is_empty() {
        vec![
            Line::from(Span::styled("No transcript yet.", overlay_muted_style())),
            Line::from(Span::styled(
                "Send your first message below and the committed history will appear here.",
                overlay_body_style(),
            )),
        ]
    } else {
        wrap_lines(&props.lines, width.max(1))
    };
    lines.push(Line::from(""));
    lines.push(overlay_divider());
    lines.push(Line::from(Span::styled(
        props.status.clone(),
        overlay_muted_style(),
    )));
    lines.push(Line::from(Span::styled(
        props.footer_hint.clone(),
        overlay_hint_style(),
    )));
    lines
}

#[cfg(test)]
mod tests {
    use ratatui::text::Line;

    use super::{overlay_lines, wrapped_line_count, TranscriptOverlayProps};

    #[test]
    fn transcript_overlay_includes_status_and_hint() {
        let props = TranscriptOverlayProps {
            title: "Transcript".to_string(),
            lines: vec![Line::from("You"), Line::from("  hello")],
            scroll: 0,
            footer_hint: "↑/↓ scroll • esc close".to_string(),
            status: "2 lines".to_string(),
        };
        let rendered = overlay_lines(&props, 40)
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
        assert!(rendered.contains("hello"));
        assert!(rendered.contains("2 lines"));
        assert!(rendered.contains("esc close"));
    }

    #[test]
    fn wrapped_line_count_reflects_wrapped_body() {
        let props = TranscriptOverlayProps {
            title: "Transcript".to_string(),
            lines: vec![Line::from(
                "This is a very long transcript row that should wrap.",
            )],
            scroll: 0,
            footer_hint: "hint".to_string(),
            status: "status".to_string(),
        };
        assert!(wrapped_line_count(&props, 24) > 3);
    }
}
