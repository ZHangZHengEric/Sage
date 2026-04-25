use crate::app::App;
use crate::bottom_pane::{command_popup, help_overlay, picker_overlay, transcript_overlay};
use crate::wrap::wrapped_height;

fn rendered_height(lines: &[ratatui::text::Line<'static>], width: u16) -> u16 {
    wrapped_height(lines, width)
}

pub(crate) fn desired_viewport_height(
    app: &App,
    width: u16,
    inline_idle_height: u16,
    inline_max_height: u16,
) -> u16 {
    let popup_height = popup_required_height(app);
    if let Some(props) = app.help_overlay_props() {
        return help_overlay::required_height(&props).clamp(
            inline_idle_height,
            inline_max_height.max(help_overlay::required_height(&props)),
        );
    }
    if let Some(props) = app.session_picker_props() {
        return picker_overlay::required_height(&props).clamp(
            inline_idle_height,
            inline_max_height.max(picker_overlay::required_height(&props)),
        );
    }
    if let Some(props) = app.transcript_overlay_props(width) {
        return transcript_overlay::required_height(&props).clamp(
            inline_idle_height,
            inline_max_height.max(transcript_overlay::required_height(&props)),
        );
    }
    let chrome_height = 4 + popup_height;
    if !app.busy {
        let idle_lines = app.rendered_idle_lines(width);
        if idle_lines.is_empty() {
            return inline_idle_height.saturating_add(popup_height);
        }
        let desired = rendered_height(&idle_lines, width).saturating_add(chrome_height);
        return desired.clamp(inline_idle_height, inline_max_height);
    }

    let live_lines = app.rendered_live_lines();
    let live_height = rendered_height(&live_lines, width);
    let desired = live_height.saturating_add(chrome_height);

    desired.clamp(inline_idle_height, inline_max_height)
}

pub(crate) fn popup_required_height(app: &App) -> u16 {
    command_popup::popup_height(app.popup_props().as_ref())
}
