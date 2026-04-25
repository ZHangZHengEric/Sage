use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use unicode_width::UnicodeWidthStr;

use crate::app::MessageKind;
use crate::markdown::render_inline;

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
            Span::styled(" to list commands, or start typing to chat with Sage.", dim),
        ]),
        Line::from(""),
    ]);
    out
}

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

pub(crate) fn render_assistant_body(text: &str) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    let raw_lines = text.lines().collect::<Vec<_>>();
    let mut index = 0usize;

    while index < raw_lines.len() {
        let raw_line = raw_lines[index];
        let trimmed = raw_line.trim_start();

        if trimmed.starts_with("```") {
            let label = trimmed.trim_start_matches("```").trim();
            let mut code_lines = Vec::new();
            index += 1;
            while index < raw_lines.len() {
                let line = raw_lines[index];
                if line.trim_start().starts_with("```") {
                    break;
                }
                code_lines.push(line);
                index += 1;
            }
            lines.extend(render_code_block(label, &code_lines));
            if index < raw_lines.len() && raw_lines[index].trim_start().starts_with("```") {
                index += 1;
            }
            continue;
        }

        if let Some((table_lines, consumed)) = parse_markdown_table(&raw_lines[index..]) {
            lines.extend(table_lines);
            index += consumed;
            continue;
        }

        if trimmed.is_empty() {
            lines.push(Line::from(""));
            index += 1;
            continue;
        }

        if let Some((level, content)) = heading_content(trimmed) {
            lines.push(Line::from({
                let mut spans = vec![Span::styled(
                    format!("{} ", "#".repeat(level)),
                    heading_style(level),
                )];
                spans.extend(render_inline(content, heading_style(level)));
                spans
            }));
            index += 1;
            continue;
        }

        if let Some(content) = trimmed.strip_prefix("> ") {
            let mut spans = vec![Span::styled(
                "│ ",
                Style::default()
                    .fg(Color::Rgb(113, 120, 125))
                    .add_modifier(Modifier::DIM),
            )];
            spans.extend(render_inline(
                content,
                Style::default()
                    .fg(Color::Rgb(170, 177, 183))
                    .add_modifier(Modifier::DIM),
            ));
            lines.push(Line::from(spans));
            index += 1;
            continue;
        }

        if let Some(content) = unordered_list_content(trimmed) {
            let mut spans = vec![Span::styled(
                "• ",
                Style::default()
                    .fg(Color::Rgb(165, 214, 110))
                    .add_modifier(Modifier::BOLD),
            )];
            spans.extend(render_inline(
                content,
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ));
            lines.push(Line::from(spans));
            index += 1;
            continue;
        }

        if let Some((marker, content)) = split_ordered_list_marker(trimmed) {
            let mut spans = vec![Span::styled(
                format!("{marker} "),
                Style::default()
                    .fg(Color::Rgb(165, 214, 110))
                    .add_modifier(Modifier::BOLD),
            )];
            spans.extend(render_inline(
                content,
                Style::default().fg(Color::Rgb(236, 240, 231)),
            ));
            lines.push(Line::from(spans));
            index += 1;
            continue;
        }

        lines.push(Line::from(render_inline(
            raw_line,
            Style::default().fg(Color::Rgb(236, 240, 231)),
        )));
        index += 1;
    }

    if lines.is_empty() {
        lines.push(Line::from(""));
    }

    lines
}

fn render_code_block(label: &str, code_lines: &[&str]) -> Vec<Line<'static>> {
    const CODE_PREVIEW_LIMIT: usize = 8;

    let mut out = Vec::new();
    let header = if label.is_empty() {
        "code".to_string()
    } else {
        format!("code {}", label)
    };
    out.push(Line::from(Span::styled(
        header,
        Style::default()
            .fg(Color::Rgb(119, 129, 141))
            .add_modifier(Modifier::DIM),
    )));

    for line in code_lines.iter().take(CODE_PREVIEW_LIMIT) {
        out.push(Line::from(Span::styled(
            line.to_string(),
            Style::default()
                .fg(Color::Rgb(169, 202, 235))
                .add_modifier(Modifier::DIM),
        )));
    }

    if code_lines.len() > CODE_PREVIEW_LIMIT {
        out.push(Line::from(Span::styled(
            format!("… {} more lines", code_lines.len() - CODE_PREVIEW_LIMIT),
            Style::default()
                .fg(Color::Rgb(119, 129, 141))
                .add_modifier(Modifier::DIM),
        )));
    }

    out
}

fn parse_markdown_table(lines: &[&str]) -> Option<(Vec<Line<'static>>, usize)> {
    if lines.len() < 2 {
        return None;
    }
    let header = parse_table_row(lines[0])?;
    if !is_table_separator(lines[1], header.len()) {
        return None;
    }

    let mut rows = vec![header];
    let mut consumed = 2usize;
    while consumed < lines.len() {
        let Some(row) = parse_table_row(lines[consumed]) else {
            break;
        };
        if row.len() != rows[0].len() {
            break;
        }
        rows.push(row);
        consumed += 1;
    }

    Some((render_table_rows(&rows), consumed))
}

fn parse_table_row(line: &str) -> Option<Vec<String>> {
    let trimmed = line.trim();
    if !trimmed.contains('|') {
        return None;
    }
    let inner = trimmed.trim_matches('|');
    let cells = inner
        .split('|')
        .map(|cell| cell.trim().to_string())
        .collect::<Vec<_>>();
    (cells.len() >= 2 && cells.iter().any(|cell| !cell.is_empty())).then_some(cells)
}

fn is_table_separator(line: &str, expected_columns: usize) -> bool {
    let trimmed = line.trim().trim_matches('|');
    let segments = trimmed.split('|').map(str::trim).collect::<Vec<_>>();
    if segments.len() != expected_columns {
        return false;
    }
    segments.iter().all(|segment| {
        !segment.is_empty()
            && segment
                .chars()
                .all(|ch| ch == '-' || ch == ':' || ch == ' ')
    })
}

fn render_table_rows(rows: &[Vec<String>]) -> Vec<Line<'static>> {
    let widths = (0..rows[0].len())
        .map(|col| {
            rows.iter()
                .map(|row| UnicodeWidthStr::width(row[col].as_str()))
                .max()
                .unwrap_or(0)
        })
        .collect::<Vec<_>>();

    let header_style = Style::default()
        .fg(Color::Rgb(165, 214, 110))
        .add_modifier(Modifier::BOLD);
    let cell_style = Style::default().fg(Color::Rgb(236, 240, 231));
    let rule_style = Style::default()
        .fg(Color::Rgb(113, 120, 125))
        .add_modifier(Modifier::DIM);

    let mut out = Vec::new();
    out.push(render_table_row(&rows[0], &widths, header_style));
    out.push(Line::from(Span::styled(table_rule(&widths), rule_style)));
    for row in rows.iter().skip(1) {
        out.push(render_table_row(row, &widths, cell_style));
    }
    out
}

fn render_table_row(row: &[String], widths: &[usize], style: Style) -> Line<'static> {
    let mut spans = Vec::new();
    for (idx, cell) in row.iter().enumerate() {
        if idx == 0 {
            spans.push(Span::styled("│ ", style));
        } else {
            spans.push(Span::styled(" │ ", style));
        }
        spans.push(Span::styled(
            format!("{:<width$}", cell, width = widths[idx]),
            style,
        ));
    }
    spans.push(Span::styled(" │", style));
    Line::from(spans)
}

fn table_rule(widths: &[usize]) -> String {
    let mut rule = String::new();
    for (idx, width) in widths.iter().enumerate() {
        if idx == 0 {
            rule.push_str("├");
        } else {
            rule.push_str("┼");
        }
        rule.push_str(&"─".repeat(width.saturating_add(2)));
    }
    rule.push('┤');
    rule
}

fn finish_lines(mut lines: Vec<Line<'static>>, trailing_blank: bool) -> Vec<Line<'static>> {
    if lines.is_empty() {
        lines.push(Line::from(""));
    }

    if trailing_blank {
        lines.push(Line::from(""));
    }

    lines
}

fn heading_content(text: &str) -> Option<(usize, &str)> {
    let hashes = text.chars().take_while(|ch| *ch == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    let content = text[hashes..].strip_prefix(' ')?;
    Some((hashes, content))
}

fn unordered_list_content(text: &str) -> Option<&str> {
    text.strip_prefix("- ")
        .or_else(|| text.strip_prefix("* "))
        .or_else(|| text.strip_prefix("+ "))
}

fn split_ordered_list_marker(text: &str) -> Option<(String, &str)> {
    let marker_len = text
        .chars()
        .take_while(|ch| ch.is_ascii_digit())
        .map(char::len_utf8)
        .sum::<usize>();

    if marker_len == 0 {
        return None;
    }

    let remainder = text.get(marker_len..)?;
    let content = remainder.strip_prefix(". ")?;
    Some((text[..marker_len + 1].to_string(), content))
}

fn heading_style(level: usize) -> Style {
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

fn user_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(127, 219, 202))
        .add_modifier(Modifier::BOLD)
}

fn assistant_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(165, 214, 110))
        .add_modifier(Modifier::BOLD)
}

fn process_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(108, 116, 112))
        .add_modifier(Modifier::DIM)
}

fn tool_title_style() -> Style {
    Style::default()
        .fg(Color::Rgb(130, 159, 189))
        .add_modifier(Modifier::DIM | Modifier::BOLD)
}

fn system_title_style() -> Style {
    Style::default()
        .fg(Color::Yellow)
        .add_modifier(Modifier::BOLD)
}

fn subtle_body_style() -> Style {
    Style::default().fg(Color::Rgb(204, 211, 205))
}

fn accent_style() -> Style {
    Style::default().fg(Color::Rgb(143, 190, 246))
}

fn card_inner_width(width: u16, max_inner_width: usize) -> Option<usize> {
    if width < 4 {
        return None;
    }
    Some(std::cmp::min(
        width.saturating_sub(4) as usize,
        max_inner_width,
    ))
}

fn with_border_with_inner_width(
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

fn line_display_width(line: &Line<'static>) -> usize {
    line.spans
        .iter()
        .map(|span| UnicodeWidthStr::width(span.content.as_ref()))
        .sum()
}

fn truncate_middle(text: &str, max_width: usize) -> String {
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

fn render_labeled_message(
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

fn indent_message_line(line: Line<'static>) -> Line<'static> {
    if line.spans.is_empty() {
        return Line::from("");
    }

    let mut spans = vec![Span::raw("  ")];
    spans.extend(line.spans);
    Line::from(spans)
}
