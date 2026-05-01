use crate::app::{ActiveSurfaceKind, App};
use crate::bottom_pane::command_popup;
use crate::bottom_pane::{composer, footer, help_overlay, picker_overlay, transcript_overlay};
use crate::custom_terminal::Frame;
use crate::ui_support::{
    command_popup_height, composer_props, footer_props, help_overlay_props, live_region_height,
    picker_overlay_props, render_live_region, transcript_overlay_props,
};
use ratatui::layout::{Constraint, Direction, Layout};

pub fn render(frame: &mut Frame, app: &App) {
    let composer_props = composer_props(app);
    let live_region_height = live_region_height(app, frame.area().width);
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(live_region_height),
            Constraint::Length(composer::composer_height(
                &composer_props,
                frame.area().width,
            )),
            Constraint::Length(command_popup_height(app)),
            Constraint::Length(1),
        ])
        .split(frame.area());

    render_live_region(frame, chunks[0], app);
    if let Some(cursor) = composer::render(frame, chunks[1], &composer_props) {
        frame.set_cursor_position(cursor);
    }
    if let Some(popup_props) = app.popup_props() {
        command_popup::render(frame, chunks[2], &popup_props);
    }
    let footer_props = footer_props(app);
    footer::render(frame, chunks[3], &footer_props);
    match app.active_surface_kind() {
        Some(ActiveSurfaceKind::Help) => {
            if let Some(props) = help_overlay_props(app) {
                help_overlay::render(frame, &props);
            }
        }
        Some(ActiveSurfaceKind::SessionPicker) => {
            if let Some(props) = picker_overlay_props(app) {
                picker_overlay::render(frame, &props);
            }
        }
        Some(ActiveSurfaceKind::Transcript) => {
            if let Some(props) = transcript_overlay_props(app, frame.area().width) {
                transcript_overlay::render(frame, &props);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use crate::app::App;
    use crate::ui_support::{footer_hint, footer_status_summary};

    #[test]
    fn busy_footer_hint_prefers_active_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("planning");

        assert_eq!(footer_hint(&app), "planning... output is streaming");
    }

    #[test]
    fn busy_footer_summary_includes_active_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("assistant_text");

        let summary = footer_status_summary(&app);
        assert!(summary.contains("phase assistant text"));
    }

    #[test]
    fn busy_footer_hint_prefers_active_tool_over_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("planning");
        app.start_tool("read_file".to_string());

        let hint = footer_hint(&app);
        assert!(hint.contains("running #1 read_file"));
        assert!(!hint.contains("planning..."));
    }

    #[test]
    fn busy_footer_hint_falls_back_without_phase_or_tool() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();

        assert_eq!(footer_hint(&app), "working... output is streaming");
    }
}
