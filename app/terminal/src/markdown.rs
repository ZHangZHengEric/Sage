use pulldown_cmark::{Event, Options, Parser, Tag};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::Span;

pub fn render_inline(text: &str, base_style: Style) -> Vec<Span<'static>> {
    if !looks_like_markdown(text) {
        return vec![Span::styled(text.to_string(), base_style)];
    }

    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);

    let parser = Parser::new_ext(text, options);
    let mut spans = Vec::new();
    let mut styles = vec![base_style];

    for event in parser {
        match event {
            Event::Start(tag) => styles.push(style_for_start_tag(tag)),
            Event::End(_end) => {
                if styles.len() > 1 {
                    let _ = styles.pop();
                }
            }
            Event::Text(content) => {
                spans.push(Span::styled(content.to_string(), compose_style(&styles)))
            }
            Event::Code(content) => spans.push(Span::styled(
                content.to_string(),
                inline_code_style(base_style),
            )),
            Event::SoftBreak | Event::HardBreak => {
                spans.push(Span::styled(" ".to_string(), compose_style(&styles)))
            }
            Event::Rule => spans.push(Span::styled("———".to_string(), compose_style(&styles))),
            Event::Html(content) | Event::InlineHtml(content) => {
                spans.push(Span::styled(content.to_string(), compose_style(&styles)))
            }
            Event::FootnoteReference(content) => {
                spans.push(Span::styled(format!("[{content}]"), compose_style(&styles)))
            }
            Event::TaskListMarker(checked) => spans.push(Span::styled(
                if checked { "[x] " } else { "[ ] " }.to_string(),
                compose_style(&styles),
            )),
            _ => {}
        }
    }

    if spans.is_empty() {
        spans.push(Span::styled(String::new(), base_style));
    }

    spans
}

fn compose_style(styles: &[Style]) -> Style {
    styles
        .iter()
        .copied()
        .fold(Style::default(), |acc, style| acc.patch(style))
}

fn style_for_start_tag(tag: Tag<'_>) -> Style {
    match tag {
        Tag::Emphasis => Style::default().add_modifier(Modifier::ITALIC),
        Tag::Strong => Style::default().add_modifier(Modifier::BOLD),
        Tag::Strikethrough => Style::default().add_modifier(Modifier::CROSSED_OUT),
        Tag::Link { .. } => Style::default()
            .fg(Color::Rgb(143, 190, 246))
            .add_modifier(Modifier::UNDERLINED),
        _ => Style::default(),
    }
}

fn inline_code_style(base_style: Style) -> Style {
    base_style.patch(
        Style::default()
            .fg(Color::Rgb(143, 190, 246))
            .add_modifier(Modifier::DIM),
    )
}

fn looks_like_markdown(text: &str) -> bool {
    ['`', '*', '_', '[', ']', '(', ')', '#', '>', '-', '+']
        .iter()
        .any(|marker| text.contains(*marker))
        || text.contains(". ")
}

#[cfg(test)]
mod tests {
    use super::render_inline;
    use ratatui::style::{Color, Style};

    #[test]
    fn plain_cjk_text_stays_single_span() {
        let spans = render_inline(
            "你好！有什么需要帮忙的吗？",
            Style::default().fg(Color::White),
        );
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].content.as_ref(), "你好！有什么需要帮忙的吗？");
    }

    #[test]
    fn inline_code_has_no_background() {
        let spans = render_inline("use `cargo run`", Style::default().fg(Color::White));
        let code = spans
            .iter()
            .find(|span| span.content.as_ref() == "cargo run")
            .expect("inline code span");
        assert_eq!(code.style.bg, None);
    }
}
