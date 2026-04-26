use crate::app::{App, FilteredSessionPicker, SessionPickerEntry, SessionPickerMode, SessionPickerState, SubmitAction};
use crate::app_preview::session_picker_preview_lines;
use crate::bottom_pane::picker_overlay;

impl App {
    pub fn open_session_picker(&mut self, mode: SessionPickerMode, items: Vec<SessionPickerEntry>) {
        self.session_picker = Some(SessionPickerState {
            mode,
            items,
            filter_query: String::new(),
            selected: 0,
        });
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.transcript_overlay = None;
        self.status = format!("session picker  {}", self.session_id);
    }

    pub fn session_picker_props(&self) -> Option<picker_overlay::PickerOverlayProps> {
        let picker = self.session_picker.as_ref()?;
        let filtered = self.filtered_session_picker_items()?;
        let selected_item = filtered
            .items
            .get(picker.selected)
            .map(|(_, item)| *item)
            .or_else(|| filtered.items.first().map(|(_, item)| *item));
        let title = match picker.mode {
            SessionPickerMode::Resume => "Resume Session",
            SessionPickerMode::Browse => "Recent Sessions",
        };
        let footer_hint = match picker.mode {
            SessionPickerMode::Resume => "type filter • ↑/↓ select • enter resume • esc close",
            SessionPickerMode::Browse => "type filter • ↑/↓ select • enter inspect • esc close",
        };
        let (preview_title, preview_lines) = selected_item
            .map(|item| {
                (
                    Some("Selected Session".to_string()),
                    session_picker_preview_lines(item, picker.mode),
                )
            })
            .unwrap_or_else(|| {
                (
                    Some("Preview".to_string()),
                    vec!["No matching sessions.".to_string()],
                )
            });
        Some(picker_overlay::PickerOverlayProps {
            title: title.to_string(),
            query: picker.filter_query.clone(),
            items: filtered
                .items
                .into_iter()
                .map(|(idx, item)| picker_overlay::PickerOverlayItem {
                    primary: item.session_id.clone(),
                    secondary: format!(
                        "{}  •  {} msgs  •  {}{}",
                        item.title,
                        item.message_count,
                        item.updated_at,
                        item.preview
                            .as_ref()
                            .map(|preview| format!("  •  {}", preview))
                            .unwrap_or_default()
                    ),
                    selected: idx == picker.selected,
                })
                .collect(),
            preview_title,
            preview_lines,
            footer_hint: footer_hint.to_string(),
        })
    }

    pub fn close_session_picker(&mut self) -> bool {
        if self.session_picker.is_none() {
            return false;
        }
        self.session_picker = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }

    pub fn is_session_picker_visible(&self) -> bool {
        self.session_picker.is_some()
    }

    pub fn select_next_session_picker_item(&mut self) -> bool {
        let visible = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        if visible == 0 {
            return false;
        }
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.selected = (picker.selected + 1) % visible;
        true
    }

    pub fn select_previous_session_picker_item(&mut self) -> bool {
        let visible = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        if visible == 0 {
            return false;
        }
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.selected = (picker.selected + visible.saturating_sub(1)) % visible;
        true
    }

    pub fn session_picker_insert_char(&mut self, ch: char) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.filter_query.push(ch);
        self.sync_session_picker_selection();
        true
    }

    pub fn session_picker_backspace(&mut self) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        if picker.filter_query.pop().is_none() {
            return false;
        }
        self.sync_session_picker_selection();
        true
    }

    pub fn clear_session_picker_filter(&mut self) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        if picker.filter_query.is_empty() {
            return false;
        }
        picker.filter_query.clear();
        self.sync_session_picker_selection();
        true
    }

    pub fn submit_session_picker_selection(&mut self) -> Option<SubmitAction> {
        let picker = self.session_picker.as_ref()?;
        let filtered = self.filtered_session_picker_items()?;
        let (_, item) = filtered.items.get(picker.selected)?;
        let session_id = item.session_id.clone();
        let mode = picker.mode;
        self.session_picker = None;
        Some(match mode {
            SessionPickerMode::Resume => SubmitAction::ResumeSession(session_id),
            SessionPickerMode::Browse => SubmitAction::ShowSession(session_id),
        })
    }

    pub(crate) fn filtered_session_picker_items(&self) -> Option<FilteredSessionPicker<'_>> {
        let picker = self.session_picker.as_ref()?;
        let query = picker.filter_query.trim().to_lowercase();
        let items = picker
            .items
            .iter()
            .enumerate()
            .filter(|(_, item)| {
                if query.is_empty() {
                    return true;
                }
                item.session_id.to_lowercase().contains(&query)
                    || item.title.to_lowercase().contains(&query)
                    || item
                        .preview
                        .as_ref()
                        .is_some_and(|preview| preview.to_lowercase().contains(&query))
            })
            .collect::<Vec<_>>();
        Some(FilteredSessionPicker { items })
    }
}
