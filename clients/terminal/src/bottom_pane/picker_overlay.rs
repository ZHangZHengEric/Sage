use ratatui::text::{Line, Span};
use ratatui::widgets::{Clear, Paragraph};

use crate::bottom_pane::{
    centered_rect, overlay_accent_style, overlay_background_style, overlay_block,
    overlay_body_style, overlay_divider, overlay_hint_style, overlay_muted_style,
};
use crate::custom_terminal::Frame;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PickerOverlayProps {
    pub(crate) title: String,
    pub(crate) query: String,
    pub(crate) items: Vec<PickerOverlayItem>,
    pub(crate) preview_title: Option<String>,
    pub(crate) preview_lines: Vec<String>,
    pub(crate) footer_hint: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PickerOverlayItem {
    pub(crate) primary: String,
    pub(crate) secondary: String,
    pub(crate) selected: bool,
}

pub(crate) fn render(frame: &mut Frame, props: &PickerOverlayProps) {
    let area = centered_rect(frame.area(), 78, required_height(props));
    frame.render_widget(Clear, area);
    frame.render_widget(
        Paragraph::new(overlay_lines(props))
            .block(overlay_block(props.title.clone()))
            .style(overlay_background_style()),
        area,
    );
}

pub(crate) fn required_height(props: &PickerOverlayProps) -> u16 {
    let item_lines = props.items.len() as u16 * 2;
    let preview_lines = if props.preview_title.is_some() || !props.preview_lines.is_empty() {
        props.preview_lines.len() as u16 + 3
    } else {
        0
    };
    (item_lines + preview_lines + 7).clamp(8, 24)
}

fn overlay_lines(props: &PickerOverlayProps) -> Vec<Line<'static>> {
    let mut lines = vec![Line::from(vec![
        Span::styled("filter: ", overlay_muted_style()),
        Span::styled(
            if props.query.is_empty() {
                "type to filter".to_string()
            } else {
                props.query.clone()
            },
            overlay_body_style(),
        ),
    ])];
    lines.push(overlay_divider());
    for item in &props.items {
        let marker = if item.selected { "› " } else { "  " };
        lines.push(Line::from(vec![
            Span::styled(
                marker,
                if item.selected {
                    overlay_accent_style()
                } else {
                    overlay_hint_style()
                },
            ),
            Span::styled(item.primary.clone(), overlay_accent_style()),
        ]));
        lines.push(Line::from(Span::styled(
            format!("  {}", item.secondary),
            overlay_body_style(),
        )));
    }
    if props.preview_title.is_some() || !props.preview_lines.is_empty() {
        lines.push(Line::from(""));
        lines.push(overlay_divider());
        lines.push(Line::from(Span::styled(
            props
                .preview_title
                .clone()
                .unwrap_or_else(|| "Preview".to_string()),
            overlay_muted_style(),
        )));
        for line in &props.preview_lines {
            lines.push(Line::from(Span::styled(line.clone(), overlay_body_style())));
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
    use super::{overlay_lines, PickerOverlayItem, PickerOverlayProps};

    #[test]
    fn overlay_lines_include_selected_marker_and_hint() {
        let props = PickerOverlayProps {
            title: "Resume Session".to_string(),
            query: "provider".to_string(),
            items: vec![
                PickerOverlayItem {
                    primary: "local-000123".to_string(),
                    secondary: "Fix provider popup  12 msgs".to_string(),
                    selected: true,
                },
                PickerOverlayItem {
                    primary: "local-000122".to_string(),
                    secondary: "Refactor footer  4 msgs".to_string(),
                    selected: false,
                },
            ],
            preview_title: Some("Preview".to_string()),
            preview_lines: vec![
                "Selected session summary".to_string(),
                "Last message preview".to_string(),
            ],
            footer_hint: "↑/↓ select • enter resume • esc close".to_string(),
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
        assert!(rendered.contains("filter: provider"));
        assert!(rendered.contains("› local-000123"));
        assert!(rendered.contains("Fix provider popup"));
        assert!(rendered.contains("Selected session summary"));
        assert!(rendered.contains("enter resume"));
    }
}
