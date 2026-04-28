use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use unicode_width::UnicodeWidthStr;

pub(crate) fn finish_lines(
    mut lines: Vec<Line<'static>>,
    trailing_blank: bool,
) -> Vec<Line<'static>> {
    if lines.is_empty() {
        lines.push(Line::from(""));
    }

    if trailing_blank {
        lines.push(Line::from(""));
    }

    lines
}

pub(crate) fn user_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(127, 219, 202))
        .add_modifier(Modifier::BOLD)
}

pub(crate) fn assistant_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(165, 214, 110))
        .add_modifier(Modifier::BOLD)
}

pub(crate) fn process_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(108, 116, 112))
        .add_modifier(Modifier::DIM)
}

pub(crate) fn tool_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(130, 159, 189))
        .add_modifier(Modifier::DIM | Modifier::BOLD)
}

pub(crate) fn system_title_style() -> Style {
    Style::default()
        .fg(Color::Yellow)
        .add_modifier(Modifier::BOLD)
}

pub(crate) fn subtle_body_style() -> Style {
    Style::default().fg(Color::Rgb(204, 211, 205))
}

pub(crate) fn accent_style() -> Style {
    Style::default().fg(Color::Rgb(143, 190, 246))
}

pub(crate) fn heading_style(level: usize) -> Style {
    match level {
        1 => Style::default()
            .fg(Color::Rgb(243, 247, 240))
            .add_modifier(Modifier::BOLD),
        2 => Style::default()
            .fg(Color::Rgb(220, 235, 205))
            .add_modifier(Modifier::BOLD),
        _ => Style::default()
            .fg(Color::Rgb(202, 214, 190))
            .add_modifier(Modifier::BOLD),
    }
}

pub(crate) fn card_inner_width(width: u16, max_inner_width: usize) -> Option<usize> {
    if width < 4 {
        return None;
    }
    Some(std::cmp::min(
        width.saturating_sub(4) as usize,
        max_inner_width,
    ))
}

pub(crate) fn with_border_with_inner_width(
    lines: Vec<Line<'static>>,
    inner_width: usize,
) -> Vec<Line<'static>> {
    let max_line_width = lines.iter().map(line_display_width).max().unwrap_or(0);
    let content_width = inner_width.max(max_line_width);

    let mut out = Vec::with_capacity(lines.len() + 2);
    out.push(
        vec![Span::styled(
            format!("╭{}╮", "─".repeat(content_width + 2)),
            Style::default()
                .fg(Color::Rgb(112, 118, 114))
                .add_modifier(Modifier::DIM),
        )]
        .into(),
    );

    for line in lines {
        let used_width = line_display_width(&line);
        let mut spans = Vec::with_capacity(line.spans.len() + 4);
        spans.push(Span::styled(
            "│ ",
            Style::default()
                .fg(Color::Rgb(112, 118, 114))
                .add_modifier(Modifier::DIM),
        ));
        spans.extend(line.spans);
        if used_width < content_width {
            spans.push(Span::raw(" ".repeat(content_width - used_width)));
        }
        spans.push(Span::styled(
            " │",
            Style::default()
                .fg(Color::Rgb(112, 118, 114))
                .add_modifier(Modifier::DIM),
        ));
        out.push(Line::from(spans));
    }

    out.push(
        vec![Span::styled(
            format!("╰{}╯", "─".repeat(content_width + 2)),
            Style::default()
                .fg(Color::Rgb(112, 118, 114))
                .add_modifier(Modifier::DIM),
        )]
        .into(),
    );
    out
}

pub(crate) fn line_display_width(line: &Line<'static>) -> usize {
    line.spans
        .iter()
        .map(|span| UnicodeWidthStr::width(span.content.as_ref()))
        .sum()
}

pub(crate) fn truncate_middle(text: &str, max_width: usize) -> String {
    if max_width == 0 || UnicodeWidthStr::width(text) <= max_width {
        return text.to_string();
    }
    if max_width <= 1 {
        return "…".to_string();
    }

    let chars: Vec<char> = text.chars().collect();
    let mut left = String::new();
    let mut right = String::new();
    let mut left_width = 0usize;
    let mut right_width = 0usize;
    let target = max_width.saturating_sub(1);

    let mut i = 0usize;
    let mut j = chars.len();
    while i < j {
        if left_width <= right_width {
            let ch = chars[i];
            let ch_width = UnicodeWidthStr::width(ch.encode_utf8(&mut [0; 4]));
            if left_width + right_width + ch_width > target {
                break;
            }
            left.push(ch);
            left_width += ch_width;
            i += 1;
        } else {
            let ch = chars[j - 1];
            let ch_width = UnicodeWidthStr::width(ch.encode_utf8(&mut [0; 4]));
            if left_width + right_width + ch_width > target {
                break;
            }
            right.insert(0, ch);
            right_width += ch_width;
            j -= 1;
        }
    }

    format!("{left}…{right}")
}

pub(crate) fn render_labeled_message(
    label: &str,
    label_style: Style,
    body_lines: Vec<Line<'static>>,
) -> Vec<Line<'static>> {
    let mut out = vec![Line::from(vec![
        Span::styled("• ", label_style),
        Span::styled(label.to_string(), label_style),
    ])];
    out.extend(body_lines.into_iter().map(indent_message_line));
    out
}

pub(crate) fn indent_message_line(line: Line<'static>) -> Line<'static> {
    if line.spans.is_empty() {
        return Line::from(vec![Span::styled(
            "  │",
            Style::default()
                .fg(Color::Rgb(95, 102, 98))
                .add_modifier(Modifier::DIM),
        )]);
    }

    let mut spans = vec![Span::styled(
        "  │ ",
        Style::default()
            .fg(Color::Rgb(95, 102, 98))
            .add_modifier(Modifier::DIM),
    )];
    spans.extend(line.spans);
    Line::from(spans)
}
