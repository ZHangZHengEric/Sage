use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::widgets::{Block, Borders};

pub(crate) mod command_popup;
pub(crate) mod composer;
pub(crate) mod footer;
pub(crate) mod help_overlay;
pub(crate) mod picker_overlay;
pub(crate) mod transcript_overlay;

const OVERLAY_BG: Color = Color::Rgb(17, 21, 20);
const OVERLAY_BORDER: Color = Color::Rgb(92, 100, 96);
const OVERLAY_TITLE: Color = Color::Rgb(235, 239, 232);

pub(crate) fn overlay_block(title: impl Into<String>) -> Block<'static> {
    Block::default()
        .title(title.into())
        .title_style(
            Style::default()
                .fg(OVERLAY_TITLE)
                .add_modifier(Modifier::BOLD),
        )
        .borders(Borders::ALL)
        .border_style(Style::default().fg(OVERLAY_BORDER))
}

pub(crate) fn overlay_background_style() -> Style {
    Style::default().bg(OVERLAY_BG)
}

pub(crate) fn centered_rect(area: Rect, max_width: u16, desired_height: u16) -> Rect {
    let width = area.width.min(max_width).max(20);
    let height = area.height.min(desired_height).max(6);
    let x = area.x + area.width.saturating_sub(width) / 2;
    let y = area.y + area.height.saturating_sub(height) / 2;
    Rect::new(x, y, width, height)
}
