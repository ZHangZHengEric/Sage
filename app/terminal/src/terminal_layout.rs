use crate::app::App;
use crate::bottom_pane::composer::{composer_height, ComposerProps};
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
    let composer_height = composer_required_height(app, width);
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

    let chrome_height = composer_height
        .saturating_add(1)
        .saturating_add(popup_height);
    if !app.busy {
        let idle_lines = app.rendered_idle_lines(width);
        if idle_lines.is_empty() {
            return composer_height
                .saturating_add(1)
                .saturating_add(popup_height)
                .clamp(inline_idle_height, inline_max_height);
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

fn composer_required_height(app: &App, width: u16) -> u16 {
    let props = ComposerProps {
        input: &app.input,
        input_cursor: app.input_cursor,
        busy: app.busy,
    };
    composer_height(&props, width)
}

#[cfg(test)]
mod tests {
    use super::desired_viewport_height;
    use crate::app::{App, MessageKind, SessionPickerEntry, SessionPickerMode, SessionPickerState};

    fn app_with_committed_transcript() -> App {
        let mut app = App::new();
        app.push_message(MessageKind::User, "hello");
        app.push_message(MessageKind::Assistant, "ready");
        let _ = app.take_pending_history_lines();
        app
    }

    #[test]
    fn help_overlay_can_expand_viewport_after_transcript_exists() {
        let mut app = app_with_committed_transcript();
        app.input = "/help".to_string();
        app.input_cursor = app.input.len();
        let _ = app.submit_input();

        let height = desired_viewport_height(&app, 100, 5, 14);

        assert!(height > 14, "height should fit help overlay, got {height}");
    }

    #[test]
    fn session_picker_can_expand_viewport_after_transcript_exists() {
        let mut app = app_with_committed_transcript();
        app.session_picker = Some(SessionPickerState {
            mode: SessionPickerMode::Browse,
            items: (0..8)
                .map(|idx| SessionPickerEntry {
                    session_id: format!("session-{idx}"),
                    title: format!("Session {idx}"),
                    message_count: idx,
                    updated_at: "now".to_string(),
                    preview: Some("preview".to_string()),
                })
                .collect(),
            filter_query: String::new(),
            selected: 0,
        });

        let height = desired_viewport_height(&app, 100, 5, 14);

        assert!(
            height > 14,
            "height should fit session picker, got {height}"
        );
    }

    #[test]
    fn transcript_overlay_can_expand_viewport_after_transcript_exists() {
        let mut app = app_with_committed_transcript();
        for idx in 0..30 {
            app.push_message(MessageKind::Assistant, format!("line {idx}"));
        }
        let _ = app.take_pending_history_lines();
        app.open_transcript_overlay();

        let height = desired_viewport_height(&app, 100, 5, 14);

        assert!(
            height > 14,
            "height should fit transcript overlay, got {height}"
        );
    }

    #[test]
    fn busy_viewport_uses_current_live_content_height() {
        let mut app = App::new();
        app.begin_task_submission("work".to_string(), true);
        app.materialize_pending_ui(100);
        let _ = app.take_clear_request();
        let _ = app.take_pending_history_lines();

        let height = desired_viewport_height(&app, 100, 5, 18);

        assert!(height < 18, "height should not leave large blank space");
        assert!(height >= 5);
    }
}
