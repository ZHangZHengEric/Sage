use crate::app::{ActiveSurfaceKind, App, SubmitAction};

impl App {
    pub fn active_surface_kind(&self) -> Option<ActiveSurfaceKind> {
        if self.help_overlay_visible {
            Some(ActiveSurfaceKind::Help)
        } else if self.session_picker.is_some() {
            Some(ActiveSurfaceKind::SessionPicker)
        } else if self.transcript_overlay.is_some() {
            Some(ActiveSurfaceKind::Transcript)
        } else if !self.popup_matches().is_empty() {
            Some(ActiveSurfaceKind::Popup)
        } else {
            None
        }
    }

    pub fn close_active_surface(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::Help) => self.close_help_overlay(),
            Some(ActiveSurfaceKind::SessionPicker) => self.close_session_picker(),
            Some(ActiveSurfaceKind::Transcript) => self.close_transcript_overlay(),
            Some(ActiveSurfaceKind::Popup) => {
                if self.input.is_empty() {
                    false
                } else {
                    self.clear_input();
                    true
                }
            }
            None => false,
        }
    }

    pub fn submit_active_surface(&mut self) -> Option<SubmitAction> {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::Help) => {
                self.close_help_overlay();
                Some(SubmitAction::Handled)
            }
            Some(ActiveSurfaceKind::SessionPicker) => self.submit_session_picker_selection(),
            Some(ActiveSurfaceKind::Transcript) => {
                self.close_transcript_overlay();
                Some(SubmitAction::Handled)
            }
            Some(ActiveSurfaceKind::Popup) => self.submit_selected_popup(),
            None => None,
        }
    }

    pub fn select_next_active_surface_item(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::SessionPicker) => self.select_next_session_picker_item(),
            Some(ActiveSurfaceKind::Transcript) => self.scroll_transcript_overlay_down(1),
            Some(ActiveSurfaceKind::Popup) => self.select_next_popup_item(),
            _ => false,
        }
    }

    pub fn select_previous_active_surface_item(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::SessionPicker) => self.select_previous_session_picker_item(),
            Some(ActiveSurfaceKind::Transcript) => self.scroll_transcript_overlay_up(1),
            Some(ActiveSurfaceKind::Popup) => self.select_previous_popup_item(),
            _ => false,
        }
    }
}
