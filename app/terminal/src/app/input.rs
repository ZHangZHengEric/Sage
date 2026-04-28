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

        self.queue_message(crate::app::MessageKind::User, text.clone());
        self.busy = true;
        self.live_message = None;
        self.live_message_had_history = false;
        self.request_started_at = Some(std::time::Instant::now());
        self.first_output_latency = None;
        self.last_request_duration = None;
        self.active_tools.clear();
        self.status = format!("running  {}", self.session_id);
        SubmitAction::RunTask(text)
    }

    pub fn insert_char(&mut self, ch: char) {
        if self.busy {
            return;
        }
        self.input.insert(self.input_cursor, ch);
        self.input_cursor += ch.len_utf8();
        self.sync_slash_popup_selection();
    }

    pub fn insert_text(&mut self, text: &str) {
        if self.busy || text.is_empty() {
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
        if self.busy || self.input_cursor == 0 {
            return;
        }
        let prev = previous_boundary(&self.input, self.input_cursor);
        self.input.drain(prev..self.input_cursor);
        self.input_cursor = prev;
        self.sync_slash_popup_selection();
    }

    pub fn delete(&mut self) {
        if self.busy || self.input_cursor >= self.input.len() {
            return;
        }
        let next = next_boundary(&self.input, self.input_cursor);
        self.input.drain(self.input_cursor..next);
        self.sync_slash_popup_selection();
    }

    pub fn move_cursor_left(&mut self) {
        self.input_cursor = previous_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_right(&mut self) {
        self.input_cursor = next_boundary(&self.input, self.input_cursor);
    }

    pub fn move_cursor_home(&mut self) {
        self.input_cursor = 0;
    }

    pub fn move_cursor_end(&mut self) {
        self.input_cursor = self.input.len();
    }

    pub fn clear_input(&mut self) {
        self.input.clear();
        self.input_cursor = 0;
        self.slash_popup_selected = 0;
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
