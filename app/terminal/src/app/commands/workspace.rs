use std::path::PathBuf;

use crate::app::{App, MessageKind};
use crate::preferences::persist_app_preferences_notice;

impl App {
    pub fn set_workspace_selection(&mut self, workspace: String) {
        let normalized = workspace.trim().to_string();
        self.set_workspace_override(Some(PathBuf::from(&normalized)));
        self.skill_catalog = None;
        persist_app_preferences_notice(self);
        self.queue_message(
            MessageKind::Tool,
            format!("workspace set: {}", self.workspace_label),
        );
        self.status = format!("workspace  {}", self.session_id);
    }

    pub fn clear_workspace_override_selection(&mut self) {
        if self.workspace_override_path().is_some() {
            self.set_workspace_override(None);
            self.skill_catalog = None;
            persist_app_preferences_notice(self);
            self.queue_message(
                MessageKind::Tool,
                format!("cleared workspace override: {}", self.workspace_label),
            );
        } else {
            self.queue_message(MessageKind::System, "no workspace override is active");
        }
        self.status = format!("workspace  {}", self.session_id);
    }

    pub fn queue_workspace_status(&mut self) {
        self.queue_message(
            MessageKind::System,
            format!("workspace: {}", self.workspace_label),
        );
        self.status = format!("workspace  {}", self.session_id);
    }
}
