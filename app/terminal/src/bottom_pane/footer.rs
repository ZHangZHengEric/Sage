use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use unicode_width::UnicodeWidthStr;

use crate::custom_terminal::Frame;

const FOOTER_BG: Color = Color::Rgb(19, 24, 22);

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct FooterProps {
    pub(crate) left_hint: String,
    pub(crate) right_summary: String,
}

pub(crate) fn render(frame: &mut Frame, area: Rect, props: &FooterProps) {
    let footer = footer_line(props, area.width as usize);
    frame.render_widget(
        Paragraph::new(footer).style(Style::default().bg(FOOTER_BG)),
        area,
    );
}

fn footer_line(props: &FooterProps, width: usize) -> Line<'static> {
    let left_width = display_width(&props.left_hint);
    let right_width = display_width(&props.right_summary);

    let hint_style = Style::default()
        .fg(Color::Rgb(146, 154, 149))
        .bg(FOOTER_BG)
        .add_modifier(Modifier::DIM);
    let status_style = Style::default()
        .fg(Color::DarkGray)
        .bg(FOOTER_BG)
        .add_modifier(Modifier::DIM);

    if width == 0 {
        return Line::default();
    }

    if left_width + right_width + 2 <= width {
        let gap = " ".repeat(width - left_width - right_width);
        return Line::from(vec![
            Span::styled(props.left_hint.clone(), hint_style),
            Span::styled(gap, status_style),
            Span::styled(props.right_summary.clone(), status_style),
        ]);
    }

    if right_width <= width {
        let leading = " ".repeat(width - right_width);
        return Line::from(vec![
            Span::styled(leading, status_style),
            Span::styled(props.right_summary.clone(), status_style),
        ]);
    }

    Line::from(Span::styled(
        truncate_left(&props.right_summary, width),
        status_style,
    ))
}

fn display_width(text: &str) -> usize {
    UnicodeWidthStr::width(text)
}

fn truncate_left(text: &str, max_width: usize) -> String {
    if max_width == 0 {
        return String::new();
    }
    if display_width(text) <= max_width {
        return text.to_string();
    }
    if max_width == 1 {
        return "…".to_string();
    }

    let budget = max_width.saturating_sub(1);
    let mut suffix = text
        .chars()
        .rev()
        .scan(0, |width, ch| {
            let ch_width = UnicodeWidthStr::width(ch.encode_utf8(&mut [0; 4]));
            if *width + ch_width > budget {
                None
            } else {
                *width += ch_width;
                Some(ch)
            }
        })
        .collect::<Vec<_>>();
    suffix.reverse();

    let mut out = String::from("…");
    out.extend(suffix);
    while display_width(&out) > max_width {
        let trimmed = out.chars().skip(1).collect::<String>();
        out = format!("…{}", trimmed.chars().skip(1).collect::<String>());
    }
    out
}

#[cfg(test)]
mod tests {
    use ratatui::buffer::Buffer;
    use ratatui::layout::Rect;
    use ratatui::style::Style;
    use ratatui::widgets::{Paragraph, Widget};

    use super::{footer_line, truncate_left, FooterProps, FOOTER_BG};

    fn line_text(line: ratatui::text::Line<'static>) -> String {
        line.spans
            .into_iter()
            .map(|span| span.content.into_owned())
            .collect::<Vec<_>>()
            .join("")
    }

    fn render_row(props: &FooterProps, area: Rect) -> String {
        let mut buffer = Buffer::empty(area);
        Paragraph::new(footer_line(props, area.width as usize))
            .style(Style::default().bg(FOOTER_BG))
            .render(area, &mut buffer);
        (0..area.width)
            .map(|x| buffer[(x, area.y)].symbol().to_string())
            .collect::<Vec<_>>()
            .join("")
    }

    fn props(left_hint: &str, right_summary: &str) -> FooterProps {
        FooterProps {
            left_hint: left_hint.to_string(),
            right_summary: right_summary.to_string(),
        }
    }

    #[test]
    fn footer_shows_hint_and_status_when_width_allows() {
        let rendered = line_text(footer_line(
            &props(
                "/help commands  •  enter send",
                "simple • Sage • ready • total 1.2s",
            ),
            96,
        ));
        assert!(rendered.contains("/help commands"));
        assert!(rendered.contains("simple"));
        assert!(rendered.contains("ready"));
    }

    #[test]
    fn footer_drops_hint_before_status_on_narrow_widths() {
        let rendered = line_text(footer_line(
            &props(
                "/help commands  •  enter send",
                "simple • Sage • ready • total 1.2s",
            ),
            24,
        ));
        assert!(!rendered.contains("/help commands"));
        assert!(rendered.contains("1.2s"));
    }

    #[test]
    fn truncate_left_preserves_tail() {
        assert_eq!(
            truncate_left("simple • workspace • ready", 14),
            "…space • ready"
        );
    }

    #[test]
    fn render_footer_row_stays_full_width() {
        let rendered = render_row(
            &props(
                "/help commands  •  enter send",
                "simple • Sage • ready • total 1.2s",
            ),
            Rect::new(0, 0, 40, 1),
        );
        assert_eq!(rendered.chars().count(), 40);
        assert!(rendered.contains("1.2s"));
    }

    #[test]
    fn render_footer_busy_prefers_status_tail() {
        let right = "simple • repo • running • total 3.4s • local-000123";
        let rendered = render_row(
            &props("working... output is streaming", right),
            Rect::new(0, 0, 28, 1),
        );
        assert!(!rendered.contains("/help commands"));
        assert!(rendered.contains("local-000123"));
    }

    #[test]
    fn footer_prefers_right_summary_tail_when_tight() {
        let right = "simple • workspace • ready • total 7.2s • ttft 1.1s";
        let rendered = line_text(footer_line(&props("running tool xyz", right), 20));
        assert!(rendered.starts_with('…'));
        assert!(rendered.contains("ttft 1.1s"));
    }
}
