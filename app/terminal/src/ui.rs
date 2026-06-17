use crate::app::{ActiveSurfaceKind, App};
use crate::bottom_pane::command_popup;
use crate::bottom_pane::{composer, footer, help_overlay, picker_overlay, transcript_overlay};
use crate::custom_terminal::Frame;
use crate::ui_support::{
    composer_props, footer_props, help_overlay_props, picker_overlay_props, render_live_region,
    transcript_overlay_props,
};
use crate::wrap::wrapped_height;
use ratatui::layout::{Constraint, Direction, Layout};

pub fn render(frame: &mut Frame, app: &App) {
    let composer_props = composer_props(app);
    let composer_height = composer::composer_height(&composer_props, frame.area().width);
    let popup_max_rows = frame
        .area()
        .height
        .saturating_sub(composer_height)
        .saturating_sub(1) as usize;
    let popup_props = app.popup_props_for_rows(popup_max_rows);
    let popup_height = command_popup::popup_height(popup_props.as_ref());
    let main_constraint = main_region_constraint(
        app,
        frame.area().width,
        frame.area().height,
        composer_height,
        popup_height,
    );
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            main_constraint,
            Constraint::Length(composer_height),
            Constraint::Length(popup_height),
            Constraint::Min(0),
            Constraint::Length(1),
        ])
        .split(frame.area());

    render_live_region(frame, chunks[0], app);
    if let Some(cursor) = composer::render(frame, chunks[1], &composer_props) {
        frame.set_cursor_position(cursor);
    }
    if let Some(popup_props) = popup_props {
        command_popup::render(frame, chunks[2], &popup_props);
    }
    let footer_props = footer_props(app);
    footer::render(frame, chunks[4], &footer_props);
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

fn main_region_constraint(
    app: &App,
    width: u16,
    height: u16,
    composer_height: u16,
    popup_height: u16,
) -> Constraint {
    if !is_empty_welcome_state(app) {
        return Constraint::Min(1);
    }

    let available = height
        .saturating_sub(composer_height)
        .saturating_sub(popup_height)
        .saturating_sub(1)
        .max(1);
    let content_height = wrapped_height(&app.rendered_main_lines(width.max(1)), width.max(1));
    Constraint::Length(content_height.clamp(1, available))
}

fn is_empty_welcome_state(app: &App) -> bool {
    app.pending_welcome_banner
        && !app.busy
        && app.committed_history_lines.is_empty()
        && app.pending_history_lines.is_empty()
}

#[cfg(test)]
mod tests {
    use crate::app::App;
    use crate::display_policy::DisplayMode;
    use crate::ui_support::{footer_hint, footer_status_summary};
    use ratatui::layout::Constraint;

    use super::{is_empty_welcome_state, main_region_constraint};

    #[test]
    fn busy_footer_hint_prefers_active_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("planning");

        assert_eq!(footer_hint(&app), "planning... output is streaming");
    }

    #[test]
    fn empty_welcome_state_uses_content_sized_main_region() {
        let app = App::new();

        assert!(is_empty_welcome_state(&app));
        assert!(matches!(
            main_region_constraint(&app, 120, 60, 3, 0),
            Constraint::Length(_)
        ));
    }

    #[test]
    fn transcript_state_uses_flexible_main_region() {
        let mut app = App::new();
        app.push_message(crate::app::MessageKind::User, "hello");
        let _ = app.take_pending_history_lines();

        assert!(!is_empty_welcome_state(&app));
        assert_eq!(
            main_region_constraint(&app, 120, 60, 3, 0),
            Constraint::Min(1)
        );
    }

    #[test]
    fn busy_footer_summary_includes_active_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("assistant_text");

        let summary = footer_status_summary(&app);
        assert!(summary.contains("phase response"));
    }

    #[test]
    fn footer_summary_includes_goal_status_when_present() {
        let mut app = App::new();
        app.set_goal_selection("ship the runtime goal contract".to_string());
        app.pending_goal_mutation = None;

        let summary = footer_status_summary(&app);
        assert!(summary.contains("goal active"));
    }

    #[test]
    fn busy_footer_hint_prefers_active_tool_over_phase() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("planning");
        app.start_tool("read_file".to_string());

        let hint = footer_hint(&app);
        assert!(hint.contains("running read_file"));
        assert!(!hint.contains("planning..."));
    }

    #[test]
    fn busy_footer_hint_keeps_phase_when_only_internal_tool_is_running() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("planning");
        app.start_tool("search_memory".to_string());

        assert_eq!(footer_hint(&app), "planning... output is streaming");
    }

    #[test]
    fn verbose_mode_keeps_raw_phase_name_in_footer() {
        let mut app = App::new();
        app.display_mode = DisplayMode::Verbose;
        app.input = "explain repo".to_string();
        let _ = app.submit_input();
        app.set_active_phase("assistant_text");

        assert_eq!(footer_hint(&app), "assistant text... output is streaming");
    }

    #[test]
    fn busy_footer_hint_falls_back_without_phase_or_tool() {
        let mut app = App::new();
        app.input = "explain repo".to_string();
        let _ = app.submit_input();

        assert_eq!(footer_hint(&app), "working... output is streaming");
    }
}
