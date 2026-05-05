use crate::app::{App, MessageKind};
use crate::display_policy::{display_mode_name, DisplayMode};
use crate::preferences::persist_app_preferences_notice;

impl App {
    pub fn set_display_mode(&mut self, mode: DisplayMode) {
        self.display_mode = mode;
        persist_app_preferences_notice(self);
        self.queue_message(
            MessageKind::Tool,
            format!("display mode set: {}", display_mode_name(mode)),
        );
        self.status = format!("display  {}", self.session_id);
    }

    pub fn queue_display_status(&mut self) {
        self.queue_message(
            MessageKind::System,
            format!(
                "display_mode: {}\nworkspace: {}",
                display_mode_name(self.display_mode),
                self.workspace_label
            ),
        );
        self.status = format!("display  {}", self.session_id);
    }
}

pub(crate) fn parse_display_mode(value: &str) -> Option<DisplayMode> {
    match value.trim().to_lowercase().as_str() {
        "compact" => Some(DisplayMode::Compact),
        "verbose" => Some(DisplayMode::Verbose),
        _ => None,
    }
}
