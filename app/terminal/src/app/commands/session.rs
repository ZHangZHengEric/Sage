use crate::app::{App, MessageKind};

impl App {
    pub fn load_resumed_session(
        &mut self,
        session_id: String,
        recent_messages: Vec<(MessageKind, String)>,
    ) {
        self.sync_session_sequence(&session_id);
        self.session_id = session_id;
        self.clear_input();
        self.busy = false;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = None;
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.last_first_output_latency = None;
        self.last_submitted_task = None;
        self.current_task = None;
        self.active_tools.clear();
        self.pending_history_lines.clear();
        self.committed_history_lines.clear();
        self.pending_welcome_banner = false;
        self.clear_requested = true;
        self.backend_restart_requested = true;
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.session_picker = None;
        self.transcript_overlay = None;
        self.provider_catalog = None;
        for (kind, message) in recent_messages {
            self.queue_message(kind, message);
        }
        self.status = format!("resumed  {}", self.session_id);
    }

    pub(crate) fn queue_welcome_banner(&mut self) {
        self.pending_welcome_banner = true;
    }

    fn sync_session_sequence(&mut self, session_id: &str) {
        let Some(raw_number) = session_id.strip_prefix("local-") else {
            return;
        };
        let Ok(number) = raw_number.parse::<u32>() else {
            return;
        };
        self.session_seq = self.session_seq.max(number.saturating_add(1));
    }
}
