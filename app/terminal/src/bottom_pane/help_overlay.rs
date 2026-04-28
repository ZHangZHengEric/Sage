use ratatui::text::{Line, Span};
use ratatui::widgets::{Clear, Paragraph};

use crate::bottom_pane::{
    centered_rect, overlay_accent_style, overlay_background_style, overlay_block,
    overlay_body_style, overlay_divider, overlay_hint_style, overlay_muted_style,
};
use crate::custom_terminal::Frame;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct HelpOverlayProps {
    pub(crate) title: String,
    pub(crate) sections: Vec<HelpSection>,
    pub(crate) footer_hint: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct HelpSection {
    pub(crate) title: String,
    pub(crate) items: Vec<HelpItem>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct HelpItem {
    pub(crate) label: String,
    pub(crate) value: String,
}

pub(crate) fn render(frame: &mut Frame, props: &HelpOverlayProps) {
    let area = centered_rect(frame.area(), 72, required_height(props));
    frame.render_widget(Clear, area);
    frame.render_widget(
        Paragraph::new(overlay_lines(props))
            .block(overlay_block(props.title.clone()))
            .style(overlay_background_style()),
        area,
    );
}

pub(crate) fn required_height(props: &HelpOverlayProps) -> u16 {
    let content_lines = props
        .sections
        .iter()
        .map(|section| section.items.len() as u16 + 1)
        .sum::<u16>();
    let section_dividers = props.sections.len().saturating_sub(1) as u16 * 2;
    (content_lines + section_dividers + 5).max(8)
}

fn overlay_lines(props: &HelpOverlayProps) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    for (section_idx, section) in props.sections.iter().enumerate() {
        if section_idx > 0 {
            lines.push(Line::from(""));
            lines.push(overlay_divider());
        }
        lines.push(Line::from(Span::styled(
            section.title.clone(),
            overlay_muted_style(),
        )));
        let label_width = section
            .items
            .iter()
            .map(|item| item.label.len())
            .max()
            .unwrap_or(0)
            .max(12);
        for item in &section.items {
            if item.label.is_empty() {
                lines.push(Line::from(Span::styled(
                    item.value.clone(),
                    overlay_body_style(),
                )));
                continue;
            }
            lines.push(Line::from(vec![
                Span::styled(
                    format!("{:<width$}", item.label, width = label_width),
                    overlay_accent_style(),
                ),
                Span::styled(item.value.clone(), overlay_body_style()),
            ]));
        }
    }
    lines.push(Line::from(""));
    lines.push(overlay_divider());
    lines.push(Line::from(Span::styled(
        props.footer_hint.clone(),
        overlay_hint_style(),
    )));
    lines
}
#[cfg(test)]
mod tests {
    use super::{overlay_lines, HelpItem, HelpOverlayProps, HelpSection};

    #[test]
    fn overlay_lines_include_commands_and_hint() {
        let props = HelpOverlayProps {
            title: "Help".to_string(),
            sections: vec![
                HelpSection {
                    title: "Commands".to_string(),
                    items: vec![
                        HelpItem {
                            label: "/help".to_string(),
                            value: "Show available commands".to_string(),
                        },
                        HelpItem {
                            label: "/resume".to_string(),
                            value: "Resume latest session".to_string(),
                        },
                    ],
                },
                HelpSection {
                    title: "Tips".to_string(),
                    items: vec![HelpItem {
                        label: String::new(),
                        value: "Use /help provider for detail.".to_string(),
                    }],
                },
            ],
            footer_hint: "esc to close".to_string(),
        };
        let rendered = overlay_lines(&props)
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
        assert!(rendered.contains("/help"));
        assert!(rendered.contains("/resume"));
        assert!(rendered.contains("Use /help provider"));
        assert!(rendered.contains("esc to close"));
    }
}
