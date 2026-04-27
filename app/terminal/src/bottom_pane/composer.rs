use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::custom_terminal::Frame;

const INPUT_BG: Color = Color::Rgb(28, 35, 32);
const INPUT_PROMPT: Color = Color::Rgb(174, 220, 121);
const INPUT_TEXT: Color = Color::Rgb(232, 237, 233);
const INPUT_HINT: Color = Color::Rgb(108, 120, 113);
const INPUT_PADDING_X: u16 = 2;

pub(crate) struct ComposerProps<'a> {
    pub(crate) input: &'a str,
    pub(crate) input_cursor: usize,
    pub(crate) busy: bool,
}

pub(crate) fn render(
    frame: &mut Frame,
    area: Rect,
    props: &ComposerProps<'_>,
) -> Option<(u16, u16)> {
    frame.render_widget(
        Paragraph::new("").style(Style::default().bg(INPUT_BG)),
        area,
    );

    let inner = inner_area(area);
    let (line, prompt_width, cursor_offset) = line_and_cursor(props, inner.width);
    frame.render_widget(
        Paragraph::new(line).style(Style::default().bg(INPUT_BG)),
        inner,
    );

    if props.busy {
        None
    } else {
        Some((inner.x + prompt_width + cursor_offset, inner.y))
    }
}

fn line_and_cursor(props: &ComposerProps<'_>, inner_width: u16) -> (Line<'static>, u16, u16) {
    let prompt = "› ";
    let prompt_width = UnicodeWidthStr::width(prompt) as u16;
    let available = inner_width.saturating_sub(prompt_width) as usize;

    let (line, cursor_offset) = if props.input.is_empty() {
        (
            Line::from(vec![
                Span::styled(
                    prompt,
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
            ]),
            0,
        )
    } else {
        let (visible, cursor_offset) = input_view(props.input, props.input_cursor, available);
        (
            Line::from(vec![
                Span::styled(
                    prompt,
                    Style::default()
                        .fg(INPUT_PROMPT)
                        .bg(INPUT_BG)
                        .add_modifier(Modifier::BOLD),
                ),
                Span::styled(visible, Style::default().fg(INPUT_TEXT).bg(INPUT_BG)),
            ]),
            cursor_offset as u16,
        )
    };

    (line, prompt_width, cursor_offset)
}

fn inner_area(area: Rect) -> Rect {
    Rect {
        x: area.x.saturating_add(INPUT_PADDING_X),
        y: area.y.saturating_add(1),
        width: area.width.saturating_sub(INPUT_PADDING_X.saturating_mul(2)),
        height: 1,
    }
}

fn input_view(text: &str, cursor: usize, max_width: usize) -> (String, usize) {
    if max_width == 0 {
        return (String::new(), 0);
    }

    let before = &text[..cursor];
    let after = &text[cursor..];
    let after_budget = max_width.min((max_width / 3).max(8));
    let (after_visible, after_truncated) = take_prefix_by_width(after, after_budget);
    let before_budget = max_width.saturating_sub(display_width(&after_visible));
    let (mut before_visible, before_truncated) = take_suffix_by_width(before, before_budget);

    let mut cursor_offset = display_width(&before_visible);
    if before_truncated && before_budget > 0 {
        before_visible.insert(0, '…');
        cursor_offset += 1;
    }

    let mut visible = before_visible;
    visible.push_str(&after_visible);
    if after_truncated && display_width(&visible) < max_width {
        visible.push('…');
    }

    while display_width(&visible) > max_width {
        let _ = visible.pop();
    }

    (visible, cursor_offset.min(max_width))
}

fn take_prefix_by_width(text: &str, max_width: usize) -> (String, bool) {
    let mut out = String::new();
    let mut width = 0;

    for ch in text.chars() {
        let ch_width = UnicodeWidthChar::width(ch).unwrap_or(0);
        if width + ch_width > max_width {
            return (out, true);
        }
        out.push(ch);
        width += ch_width;
    }

    (out, false)
}

fn take_suffix_by_width(text: &str, max_width: usize) -> (String, bool) {
    let total = display_width(text);
    if total <= max_width {
        return (text.to_string(), false);
    }

    let mut width = 0;
    let mut start = text.len();
    for (idx, ch) in text.char_indices().rev() {
        let ch_width = UnicodeWidthChar::width(ch).unwrap_or(0);
        if width + ch_width > max_width {
            break;
        }
        width += ch_width;
        start = idx;
    }

    (text[start..].to_string(), true)
}

fn display_width(text: &str) -> usize {
    UnicodeWidthStr::width(text)
}

#[cfg(test)]
mod tests {
    use ratatui::buffer::Buffer;
    use ratatui::layout::Rect;
    use ratatui::style::Style;
    use ratatui::widgets::{Paragraph, Widget};

    use super::{inner_area, line_and_cursor, ComposerProps, INPUT_BG};

    fn render_row(props: &ComposerProps<'_>, area: Rect) -> (String, Option<(u16, u16)>) {
        let mut buffer = Buffer::empty(area);
        Paragraph::new("")
            .style(Style::default().bg(INPUT_BG))
            .render(area, &mut buffer);
        let inner = inner_area(area);
        let (line, prompt_width, cursor_offset) = line_and_cursor(props, inner.width);
        Paragraph::new(line)
            .style(Style::default().bg(INPUT_BG))
            .render(inner, &mut buffer);
        let cursor = if props.busy {
            None
        } else {
            Some((inner.x + prompt_width + cursor_offset, inner.y))
        };
        let row_y = inner.y;
        let row = (0..area.width)
            .map(|x| buffer[(x, row_y)].symbol().to_string())
            .collect::<Vec<_>>()
            .join("");
        (row, cursor)
    }

    #[test]
    fn render_idle_placeholder_and_cursor() {
        let props = ComposerProps {
            input: "",
            input_cursor: 0,
            busy: false,
        };
        let (row, cursor) = render_row(&props, Rect::new(0, 0, 56, 3));
        assert!(row.contains("› Ask Sage to inspect"));
        assert_eq!(cursor, Some((4, 1)));
    }

    #[test]
    fn render_busy_placeholder_hides_cursor() {
        let props = ComposerProps {
            input: "",
            input_cursor: 0,
            busy: true,
        };
        let (row, cursor) = render_row(&props, Rect::new(0, 0, 32, 3));
        assert!(row.contains("› Sage is working..."));
        assert_eq!(cursor, None);
    }

    #[test]
    fn render_long_input_keeps_visible_tail() {
        let input = "this is a very long draft for composer rendering";
        let props = ComposerProps {
            input,
            input_cursor: input.len(),
            busy: false,
        };
        let (row, cursor) = render_row(&props, Rect::new(0, 0, 24, 3));
        assert!(row.contains("…composer rend"));
        assert_eq!(cursor, Some((22, 1)));
    }
}
