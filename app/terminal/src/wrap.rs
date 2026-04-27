use std::ops::Range;

use ratatui::style::Style;
use ratatui::text::{Line, Span};
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

pub fn wrap_lines(lines: &[Line<'static>], width: u16) -> Vec<Line<'static>> {
    let width = width.max(1) as usize;
    let mut wrapped = Vec::new();

    for line in lines {
        wrapped.extend(wrap_line(line, width));
    }

    wrapped
}

pub fn wrapped_height(lines: &[Line<'static>], width: u16) -> u16 {
    wrap_lines(lines, width).len().min(u16::MAX as usize) as u16
}

fn wrap_line(line: &Line<'static>, width: usize) -> Vec<Line<'static>> {
    if line.spans.is_empty() {
        return vec![Line::default()
            .style(line.style)
            .alignment_opt(line.alignment)];
    }

    let (flat, span_bounds) = flatten_line(line);
    if flat.is_empty() {
        return vec![Line::from("")
            .style(line.style)
            .alignment_opt(line.alignment)];
    }

    let hanging_indent = hanging_indent(&flat);
    let indent_width = UnicodeWidthStr::width(hanging_indent.as_str());
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut first = true;

    while start < flat.len() {
        let available = if first {
            width.max(1)
        } else {
            width.saturating_sub(indent_width).max(1)
        };

        let (end, next_start) = next_wrap_range(&flat, start, available);
        let mut wrapped = if first {
            slice_line(line, &span_bounds, start..end)
        } else {
            let mut spans = vec![Span::raw(hanging_indent.clone())];
            spans.extend(slice_line(line, &span_bounds, start..end).spans);
            Line::from(spans)
        };
        wrapped.style = line.style;
        wrapped.alignment = line.alignment;
        out.push(wrapped);

        if next_start <= start {
            break;
        }
        start = next_start;
        first = false;
    }

    if out.is_empty() {
        out.push(
            Line::from("")
                .style(line.style)
                .alignment_opt(line.alignment),
        );
    }

    out
}

fn flatten_line(line: &Line<'static>) -> (String, Vec<(Range<usize>, Style)>) {
    let mut flat = String::new();
    let mut bounds = Vec::with_capacity(line.spans.len());
    let mut offset = 0usize;

    for span in &line.spans {
        let text = span.content.as_ref();
        let start = offset;
        flat.push_str(text);
        offset += text.len();
        bounds.push((start..offset, span.style));
    }

    (flat, bounds)
}

fn slice_line(
    line: &Line<'static>,
    bounds: &[(Range<usize>, Style)],
    range: Range<usize>,
) -> Line<'static> {
    if range.is_empty() {
        return Line::from("");
    }

    let mut spans = Vec::new();
    for (span, (span_range, style)) in line.spans.iter().zip(bounds.iter()) {
        let start = range.start.max(span_range.start);
        let end = range.end.min(span_range.end);
        if start >= end {
            continue;
        }

        let local_start = start - span_range.start;
        let local_end = end - span_range.start;
        spans.push(Span::styled(
            span.content[local_start..local_end].to_string(),
            *style,
        ));
    }

    Line::from(spans)
}

fn next_wrap_range(text: &str, start: usize, max_width: usize) -> (usize, usize) {
    let mut width = 0usize;
    let mut last_break = None;
    let mut idx = start;
    let mut saw_non_whitespace = false;
    let mut in_whitespace = false;
    let mut whitespace_start = start;

    for (offset, ch) in text[start..].char_indices() {
        let absolute = start + offset;
        let ch_width = char_width(ch);

        if width + ch_width > max_width && absolute > start {
            if let Some(break_idx) = last_break {
                let next = skip_wrapped_whitespace(text, break_idx);
                return (break_idx, next.max(break_idx));
            }
            return (absolute, absolute);
        }

        width += ch_width;
        idx = absolute + ch.len_utf8();

        if ch.is_whitespace() {
            if !in_whitespace {
                whitespace_start = absolute;
                in_whitespace = true;
            }
            if saw_non_whitespace {
                last_break = Some(whitespace_start);
            }
        } else {
            saw_non_whitespace = true;
            in_whitespace = false;
        }
    }

    (idx, idx)
}

fn skip_wrapped_whitespace(text: &str, index: usize) -> usize {
    let mut cursor = index;
    for ch in text[index..].chars() {
        if !ch.is_whitespace() {
            break;
        }
        cursor += ch.len_utf8();
    }
    cursor
}

fn hanging_indent(text: &str) -> String {
    let leading = text
        .chars()
        .take_while(|ch| ch.is_whitespace())
        .collect::<String>();
    let rest = &text[leading.len()..];

    if rest.is_empty() {
        return leading;
    }

    let extra = if let Some(extra) = marker_indent(rest) {
        extra
    } else {
        0
    };

    format!("{leading}{}", " ".repeat(extra))
}

fn marker_indent(text: &str) -> Option<usize> {
    for marker in ["› ", "• ", "· ", "! ", "> ", "│ ", "- ", "* ", "+ "] {
        if text.starts_with(marker) {
            return Some(UnicodeWidthStr::width(marker));
        }
    }

    let digits = text
        .chars()
        .take_while(|ch| ch.is_ascii_digit())
        .map(char::len_utf8)
        .sum::<usize>();
    if digits == 0 {
        return None;
    }

    let remainder = text.get(digits..)?;
    if let Some(rest) = remainder
        .strip_prefix(". ")
        .or_else(|| remainder.strip_prefix(") "))
    {
        let marker_width = UnicodeWidthStr::width(&text[..text.len() - rest.len()]);
        return Some(marker_width);
    }

    None
}

fn char_width(ch: char) -> usize {
    match ch {
        '\t' => 4,
        _ => UnicodeWidthChar::width(ch).unwrap_or(0).max(1),
    }
}

trait LineAlignmentExt {
    fn alignment_opt(self, alignment: Option<ratatui::layout::Alignment>) -> Self;
}

impl LineAlignmentExt for Line<'static> {
    fn alignment_opt(mut self, alignment: Option<ratatui::layout::Alignment>) -> Self {
        self.alignment = alignment;
        self
    }
}

#[cfg(test)]
mod tests {
    use super::{wrap_lines, wrapped_height};
    use ratatui::style::{Color, Style, Stylize};
    use ratatui::text::Line;

    fn concat(line: &Line<'static>) -> String {
        line.spans
            .iter()
            .map(|span| span.content.as_ref())
            .collect()
    }

    #[test]
    fn wraps_cjk_by_display_width_without_extra_spacing() {
        let sample = "mixed中英文本渲染测试。";
        let wrapped = wrap_lines(&[Line::from(sample)], 10);
        assert!(wrapped.len() >= 2);
        let joined = wrapped.iter().map(concat).collect::<Vec<_>>().join("");
        assert_eq!(joined, sample);
        assert!(!wrapped.iter().any(|line| concat(line).contains("中 英")));
    }

    #[test]
    fn preserves_hanging_indent_for_bullets() {
        let wrapped = wrap_lines(&[Line::from("  • this is a fairly long bullet item")], 14);
        assert_eq!(concat(&wrapped[0]), "  • this is a");
        assert_eq!(concat(&wrapped[1]), "    fairly");
        assert_eq!(concat(&wrapped[2]), "    long");
        assert_eq!(concat(&wrapped[3]), "    bullet");
        assert_eq!(concat(&wrapped[4]), "    item");
    }

    #[test]
    fn preserves_span_styles_when_wrapping() {
        let wrapped = wrap_lines(&[Line::from(vec!["hello ".red(), "world".into()])], 6);
        assert_eq!(wrapped.len(), 2);
        assert_eq!(wrapped[0].spans[0].style.fg, Some(Color::Red));
        assert_eq!(concat(&wrapped[0]), "hello");
        assert_eq!(concat(&wrapped[1]), "world");
    }

    #[test]
    fn wrapped_height_matches_wrapped_lines() {
        let lines = vec![Line::from("hello world"), Line::from("foo bar baz")];
        assert_eq!(
            wrapped_height(&lines, 6),
            wrap_lines(&lines, 6).len() as u16
        );
    }

    #[test]
    fn empty_line_still_renders_one_row() {
        let wrapped = wrap_lines(&[Line::from("").style(Style::default())], 10);
        assert_eq!(wrapped.len(), 1);
        assert_eq!(concat(&wrapped[0]), "");
    }
}
