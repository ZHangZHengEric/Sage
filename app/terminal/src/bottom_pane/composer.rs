use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Clear, Paragraph};
use unicode_width::UnicodeWidthStr;

use crate::custom_terminal::Frame;
use crate::wrap::{wrap_lines, wrapped_height};

const INPUT_BG: Color = Color::Rgb(28, 35, 32);
const INPUT_PROMPT: Color = Color::Rgb(174, 220, 121);
const INPUT_TEXT: Color = Color::Rgb(232, 237, 233);
const INPUT_HINT: Color = Color::Rgb(108, 120, 113);
const INPUT_PADDING_X: u16 = 2;
const INPUT_PADDING_Y: u16 = 1;
const CONTINUATION_PREFIX: &str = "  ";
const MAX_COMPOSER_BODY_LINES: u16 = 5;

pub(crate) struct ComposerProps<'a> {
    pub(crate) input: &'a str,
    pub(crate) input_cursor: usize,
    pub(crate) busy: bool,
}

pub(crate) fn composer_height(props: &ComposerProps<'_>, width: u16) -> u16 {
    let body_width = inner_width(width);
    let body_lines = composer_body_lines(props, body_width);
    body_lines
        .saturating_add(INPUT_PADDING_Y.saturating_mul(2))
        .clamp(
            3,
            MAX_COMPOSER_BODY_LINES.saturating_add(INPUT_PADDING_Y.saturating_mul(2)),
        )
}

pub(crate) fn render(
    frame: &mut Frame,
    area: Rect,
    props: &ComposerProps<'_>,
) -> Option<(u16, u16)> {
    frame.render_widget(Clear, area);
    frame.render_widget(Block::default().style(Style::default().bg(INPUT_BG)), area);

    let inner = inner_area(area);
    let lines = composer_lines(props);
    let wrapped = visible_wrapped_lines(&lines, inner.width.max(1));
    frame.render_widget(
        Paragraph::new(wrapped.clone()).style(Style::default().bg(INPUT_BG)),
        inner,
    );

    if props.busy {
        None
    } else {
        let (cursor_col, cursor_row) = cursor_position(props, inner.width.max(1));
        Some((inner.x + cursor_col, inner.y + cursor_row))
    }
}

fn composer_lines(props: &ComposerProps<'_>) -> Vec<Line<'static>> {
    if props.input.is_empty() {
        return vec![Line::from(vec![
            Span::styled(
                "› ",
                Style::default()
                    .fg(INPUT_PROMPT)
                    .bg(INPUT_BG)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                if props.busy {
                    "Sage is working..."
                } else {
                    "Ask Sage to inspect, edit, or explain this repo"
                },
                Style::default()
                    .fg(INPUT_HINT)
                    .bg(INPUT_BG)
                    .add_modifier(Modifier::DIM),
            ),
        ])];
    }

    let mut out = Vec::new();
    for (idx, line) in props.input.split('\n').enumerate() {
        let prefix = if idx == 0 {
            "› "
        } else {
            CONTINUATION_PREFIX
        };
        let prefix_style = if idx == 0 {
            Style::default()
                .fg(INPUT_PROMPT)
                .bg(INPUT_BG)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default()
                .fg(INPUT_HINT)
                .bg(INPUT_BG)
                .add_modifier(Modifier::DIM)
        };

        let mut spans = vec![Span::styled(prefix, prefix_style)];
        if line.is_empty() {
            spans.push(Span::styled(
                "",
                Style::default().fg(INPUT_TEXT).bg(INPUT_BG),
            ));
        } else {
            spans.push(Span::styled(
                line.to_string(),
                Style::default().fg(INPUT_TEXT).bg(INPUT_BG),
            ));
        }
        out.push(Line::from(spans));
    }

    if out.is_empty() {
        out.push(Line::from(""));
    }
    out
}

fn cursor_position(props: &ComposerProps<'_>, inner_width: u16) -> (u16, u16) {
    let before_cursor = &props.input[..props.input_cursor];
    let lines = if before_cursor.is_empty() {
        vec![Line::from(vec![Span::styled(
            "› ",
            Style::default()
                .fg(INPUT_PROMPT)
                .bg(INPUT_BG)
                .add_modifier(Modifier::BOLD),
        )])]
    } else {
        let mut out = Vec::new();
        for (idx, line) in before_cursor.split('\n').enumerate() {
            let prefix = if idx == 0 {
                "› "
            } else {
                CONTINUATION_PREFIX
            };
            out.push(Line::from(format!("{prefix}{line}")));
        }
        out
    };

    let wrapped = visible_wrapped_lines(&lines, inner_width.max(1));
    let last = wrapped.last().cloned().unwrap_or_else(|| Line::from("› "));
    let col = line_width(&last).min(inner_width as usize) as u16;
    let row = wrapped.len().saturating_sub(1).min(u16::MAX as usize) as u16;
    (col, row)
}

fn composer_body_lines(props: &ComposerProps<'_>, body_width: u16) -> u16 {
    wrapped_height(&composer_lines(props), body_width.max(1)).clamp(1, MAX_COMPOSER_BODY_LINES)
}

fn visible_wrapped_lines(lines: &[Line<'static>], width: u16) -> Vec<Line<'static>> {
    let wrapped = wrap_lines(lines, width.max(1));
    let max_lines = MAX_COMPOSER_BODY_LINES as usize;
    if wrapped.len() <= max_lines {
        wrapped
    } else {
        wrapped[..max_lines].to_vec()
    }
}

fn inner_area(area: Rect) -> Rect {
    Rect {
        x: area.x.saturating_add(INPUT_PADDING_X),
        y: area.y.saturating_add(INPUT_PADDING_Y),
        width: area.width.saturating_sub(INPUT_PADDING_X.saturating_mul(2)),
        height: area
            .height
            .saturating_sub(INPUT_PADDING_Y.saturating_mul(2)),
    }
}

fn inner_width(width: u16) -> u16 {
    width
        .saturating_sub(INPUT_PADDING_X.saturating_mul(2))
        .max(1)
}

fn line_width(line: &Line<'static>) -> usize {
    line.spans
        .iter()
        .map(|span| UnicodeWidthStr::width(span.content.as_ref()))
        .sum()
}

#[cfg(test)]
mod tests {
    use ratatui::buffer::Buffer;
    use ratatui::layout::Rect;
    use ratatui::style::Style;
    use ratatui::widgets::{Paragraph, Widget};

    use super::{
        composer_height, composer_lines, cursor_position, inner_area, visible_wrapped_lines,
        ComposerProps, INPUT_BG,
    };

    fn render_rows(props: &ComposerProps<'_>, area: Rect) -> (Vec<String>, Option<(u16, u16)>) {
        let mut buffer = Buffer::empty(area);
        Paragraph::new("")
            .style(Style::default().bg(INPUT_BG))
            .render(area, &mut buffer);
        let inner = inner_area(area);
        let wrapped = visible_wrapped_lines(&composer_lines(props), inner.width.max(1));
        Paragraph::new(wrapped)
            .style(Style::default().bg(INPUT_BG))
            .render(inner, &mut buffer);
        let cursor = if props.busy {
            None
        } else {
            let (cursor_col, cursor_row) = cursor_position(props, inner.width.max(1));
            Some((inner.x + cursor_col, inner.y + cursor_row))
        };
        let rows = (0..area.height)
            .map(|y| {
                (0..area.width)
                    .map(|x| buffer[(x, y)].symbol().to_string())
                    .collect::<Vec<_>>()
                    .join("")
            })
            .collect::<Vec<_>>();
        (rows, cursor)
    }

    #[test]
    fn render_idle_placeholder_and_cursor() {
        let props = ComposerProps {
            input: "",
            input_cursor: 0,
            busy: false,
        };
        let (rows, cursor) = render_rows(&props, Rect::new(0, 0, 56, 3));
        assert!(rows.join("\n").contains("› Ask Sage to inspect"));
        assert_eq!(cursor, Some((4, 1)));
    }

    #[test]
    fn render_busy_placeholder_hides_cursor() {
        let props = ComposerProps {
            input: "",
            input_cursor: 0,
            busy: true,
        };
        let (rows, cursor) = render_rows(&props, Rect::new(0, 0, 32, 3));
        assert!(rows.join("\n").contains("› Sage is working..."));
        assert_eq!(cursor, None);
    }

    #[test]
    fn render_long_input_wraps_visible_content() {
        let input = "this is a very long draft for composer rendering";
        let props = ComposerProps {
            input,
            input_cursor: input.len(),
            busy: false,
        };
        let (rows, cursor) = render_rows(&props, Rect::new(0, 0, 24, 4));
        let rendered = rows.join("\n");
        assert!(rendered.contains("this is a very"));
        assert!(rendered.contains("draft for"));
        assert!(cursor.is_some());
    }

    #[test]
    fn render_multiline_input_places_cursor_on_next_line() {
        let input = "first line\nsecond";
        let props = ComposerProps {
            input,
            input_cursor: input.len(),
            busy: false,
        };
        let (rows, cursor) = render_rows(&props, Rect::new(0, 0, 32, 5));
        assert!(rows.join("\n").contains("first line"));
        assert!(rows.join("\n").contains("second"));
        assert_eq!(cursor, Some((10, 2)));
    }

    #[test]
    fn trailing_newline_does_not_push_cursor_below_visible_lines() {
        let input = "\n\n\n\n\n";
        let props = ComposerProps {
            input,
            input_cursor: input.len(),
            busy: false,
        };
        let area = Rect::new(0, 0, 28, composer_height(&props, 28));
        let (_, cursor) = render_rows(&props, area);
        let (_, cursor_y) = cursor.expect("cursor should stay visible");
        assert!(cursor_y < area.height);
    }

    #[test]
    fn composer_height_grows_for_multiline_input() {
        let props = ComposerProps {
            input: "one\ntwo\nthree",
            input_cursor: "one\ntwo\nthree".len(),
            busy: false,
        };
        assert!(composer_height(&props, 40) > 3);
    }

    #[test]
    fn render_long_multiline_input_keeps_cursor_inside_visible_window() {
        let input = "one\ntwo\nthree\nfour\nfive\nsix\nseven";
        let props = ComposerProps {
            input,
            input_cursor: input.len(),
            busy: false,
        };
        let area = Rect::new(0, 0, 28, composer_height(&props, 28));
        let (rows, cursor) = render_rows(&props, area);
        let rendered = rows.join("\n");
        assert!(rendered.contains("one"));
        assert!(!rendered.contains("seven"));
        let (_, cursor_y) = cursor.expect("cursor should stay visible");
        assert!(cursor_y < area.height);
    }
}
