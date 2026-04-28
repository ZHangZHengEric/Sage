use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use unicode_width::UnicodeWidthStr;

use crate::markdown::render_inline;

use super::common::heading_style;

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
    out.push(Line::from(vec![Span::styled(
        format!("╭─ {header}"),
        Style::default()
            .fg(Color::Rgb(119, 129, 141))
            .add_modifier(Modifier::DIM),
    )]));

    for line in code_lines.iter().take(CODE_PREVIEW_LIMIT) {
        out.push(Line::from(vec![
            Span::styled(
                "│ ",
                Style::default()
                    .fg(Color::Rgb(95, 107, 118))
                    .add_modifier(Modifier::DIM),
            ),
            Span::styled(
                line.to_string(),
                Style::default()
                    .fg(Color::Rgb(169, 202, 235))
                    .add_modifier(Modifier::DIM),
            ),
        ]));
    }

    if code_lines.len() > CODE_PREVIEW_LIMIT {
        out.push(Line::from(vec![
            Span::styled(
                "│ ",
                Style::default()
                    .fg(Color::Rgb(95, 107, 118))
                    .add_modifier(Modifier::DIM),
            ),
            Span::styled(
                format!("… {} more lines", code_lines.len() - CODE_PREVIEW_LIMIT),
                Style::default()
                    .fg(Color::Rgb(119, 129, 141))
                    .add_modifier(Modifier::DIM),
            ),
        ]));
    }

    out.push(Line::from(Span::styled(
        format!(
            "╰─ {} lines shown",
            code_lines.len().min(CODE_PREVIEW_LIMIT)
        ),
        Style::default()
            .fg(Color::Rgb(95, 107, 118))
            .add_modifier(Modifier::DIM),
    )));

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
