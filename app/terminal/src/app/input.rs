use crate::app::{App, SubmitAction};

impl App {
    pub fn submit_input(&mut self) -> SubmitAction {
        let raw = self.input.clone();
        if raw.trim().is_empty() {
            return SubmitAction::Noop;
        }
        let text = raw.trim_end().to_string();

        self.clear_input();

        if text.starts_with('/') {
            return self.handle_command(&text);
        }

        self.begin_task_submission(text.clone(), true);
        SubmitAction::RunTask(text)
    }

    pub(crate) fn begin_task_submission(&mut self, task: String, queue_user_message: bool) {
        self.ensure_local_session();
        if queue_user_message {
            self.queue_message(crate::app::MessageKind::User, task.clone());
        }
        self.record_input_history(&task);
        self.last_submitted_task = Some(task.clone());
        self.current_task = Some(task);
        self.busy = true;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = Some(std::time::Instant::now());
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.last_first_output_latency = None;
        self.pending_backend_stats = None;
        self.active_phase = None;
        self.active_tools.clear();
        self.tool_step_seq = 0;
        self.status = format!("running  {}", self.session_label());
    }

    pub fn insert_char(&mut self, ch: char) {
        if self.busy && !(self.input.starts_with('/') || ch == '/') {
            return;
        }
        self.input.insert(self.input_cursor, ch);
        self.input_cursor += ch.len_utf8();
        self.sync_slash_popup_selection();
    }

    pub fn insert_text(&mut self, text: &str) {
        if text.is_empty() {
            return;
        }
        if self.busy && !(self.input.starts_with('/') || text.starts_with('/')) {
            return;
        }
        self.input.insert_str(self.input_cursor, text);
        self.input_cursor += text.len();
        self.sync_slash_popup_selection();
    }

    pub fn insert_newline(&mut self) {
        self.insert_char('\n');
    }

    pub fn backspace(&mut self) {
        if (self.busy && !self.input.starts_with('/')) || self.input_cursor == 0 {
            return;
        }
        let prev = previous_boundary(&self.input, self.input_cursor);
        self.input.drain(prev..self.input_cursor);
        self.input_cursor = prev;
        self.sync_slash_popup_selection();
    }

    pub fn delete(&mut self) {
        if (self.busy && !self.input.starts_with('/')) || self.input_cursor >= self.input.len() {
            return;
        }
        let next = next_boundary(&self.input, self.input_cursor);
        self.input.drain(self.input_cursor..next);
        self.sync_slash_popup_selection();
    }

    pub fn move_cursor_left(&mut self) {
        if self.busy && !self.input.starts_with('/') {
            return;
        }
        self.input_cursor = previous_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_right(&mut self) {
        if self.busy && !self.input.starts_with('/') {
            return;
        }
        self.input_cursor = next_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_home(&mut self) {
        if self.busy && !self.input.starts_with('/') {
            return;
        }
        self.input_cursor = 0;
    }

    pub fn move_cursor_end(&mut self) {
        if self.busy && !self.input.starts_with('/') {
            return;
        }
        self.input_cursor = self.input.len();
    }

    pub fn clear_input(&mut self) {
        self.input.clear();
        self.input_cursor = 0;
        self.slash_popup_selected = 0;
        self.input_history_index = None;
        self.input_history_draft = None;
    }

    pub fn select_previous_input_history(&mut self) -> bool {
        if self.busy && !self.input.starts_with('/') {
            return false;
        }
        if self.input_history.is_empty() {
            return false;
        }

        let next_index = match self.input_history_index {
            Some(0) => 0,
            Some(index) => index.saturating_sub(1),
            None => {
                self.input_history_draft = Some(self.input.clone());
                self.input_history.len().saturating_sub(1)
            }
        };
        self.input_history_index = Some(next_index);
        self.input = self.input_history[next_index].clone();
        self.input_cursor = self.input.len();
        self.sync_slash_popup_selection();
        true
    }

    pub fn select_next_input_history(&mut self) -> bool {
        if self.busy && !self.input.starts_with('/') {
            return false;
        }
        let Some(index) = self.input_history_index else {
            return false;
        };

        if index + 1 >= self.input_history.len() {
            self.input_history_index = None;
            self.input = self.input_history_draft.take().unwrap_or_default();
        } else {
            let next_index = index + 1;
            self.input_history_index = Some(next_index);
            self.input = self.input_history[next_index].clone();
        }
        self.input_cursor = self.input.len();
        self.sync_slash_popup_selection();
        true
    }

    pub(super) fn sync_slash_popup_selection(&mut self) {
        if self.help_overlay_visible || self.session_picker.is_some() {
            self.slash_popup_selected = 0;
            return;
        }
        let len = self.popup_matches().len();
        if len == 0 {
            self.slash_popup_selected = 0;
        } else {
            self.slash_popup_selected = self.slash_popup_selected.min(len.saturating_sub(1));
        }
    }

    pub(super) fn sync_session_picker_selection(&mut self) {
        let len = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        let Some(picker) = self.session_picker.as_mut() else {
            return;
        };
        if len == 0 {
            picker.selected = 0;
        } else {
            picker.selected = picker.selected.min(len.saturating_sub(1));
        }
    }

    fn record_input_history(&mut self, task: &str) {
        let normalized = task.trim();
        if normalized.is_empty() {
            self.input_history_index = None;
            self.input_history_draft = None;
            return;
        }
        if self
            .input_history
            .last()
            .map(|entry| entry == normalized)
            .unwrap_or(false)
        {
            self.input_history_index = None;
            self.input_history_draft = None;
            return;
        }
        self.input_history.push(normalized.to_string());
        self.input_history_index = None;
        self.input_history_draft = None;
    }
}

fn previous_boundary(text: &str, index: usize) -> usize {
    if index == 0 {
        return 0;
    }
    text[..index]
        .char_indices()
        .last()
        .map(|(idx, _)| idx)
        .unwrap_or(0)
}

fn next_boundary(text: &str, index: usize) -> usize {
    if index >= text.len() {
        return text.len();
    }
    let mut iter = text[index..].char_indices();
    let _ = iter.next();
    index
        + iter
            .next()
            .map(|(offset, _)| offset)
            .unwrap_or(text[index..].len())
}
