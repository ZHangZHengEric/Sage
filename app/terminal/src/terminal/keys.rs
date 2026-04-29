use anyhow::Result;
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::app::{ActiveSurfaceKind, App};
use crate::backend::BackendHandle;
use crate::terminal_support::sync_contextual_popup_data;

use super::handle_submit_action;

pub(super) fn handle_key(
    app: &mut App,
    key: KeyEvent,
    backend: &mut Option<BackendHandle>,
) -> Result<bool> {
    match app.active_surface_kind() {
        Some(ActiveSurfaceKind::SessionPicker) => match key.code {
            KeyCode::Enter => {
                if let Some(action) = app.submit_active_surface() {
                    return handle_submit_action(app, backend, action);
                }
                return Ok(false);
            }
            KeyCode::Up => return Ok(app.select_previous_active_surface_item()),
            KeyCode::Down => return Ok(app.select_next_active_surface_item()),
            KeyCode::Backspace => return Ok(app.session_picker_backspace()),
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                app.should_quit = true;
                return Ok(true);
            }
            KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                return Ok(app.clear_session_picker_filter());
            }
            KeyCode::Char(ch) => return Ok(app.session_picker_insert_char(ch)),
            KeyCode::Esc => return Ok(app.close_active_surface()),
            _ => return Ok(true),
        },
        Some(ActiveSurfaceKind::Transcript) => match key.code {
            KeyCode::Esc | KeyCode::Enter => return Ok(app.close_active_surface()),
            KeyCode::Up => return Ok(app.select_previous_active_surface_item()),
            KeyCode::Down => return Ok(app.select_next_active_surface_item()),
            KeyCode::PageUp => return Ok(app.page_transcript_overlay_up(8)),
            KeyCode::PageDown => return Ok(app.page_transcript_overlay_down(8)),
            KeyCode::Home => return Ok(app.scroll_transcript_overlay_up(u16::MAX)),
            KeyCode::End => return Ok(app.scroll_transcript_overlay_down(u16::MAX)),
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                app.should_quit = true;
                return Ok(true);
            }
            _ => return Ok(true),
        },
        Some(ActiveSurfaceKind::Help) => match key.code {
            KeyCode::Esc | KeyCode::Enter => return Ok(app.close_active_surface()),
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                app.should_quit = true;
                return Ok(true);
            }
            _ => return Ok(true),
        },
        _ => {}
    }

    match key.code {
        KeyCode::Enter if key.modifiers.contains(KeyModifiers::SHIFT) => {
            if app.busy {
                return Ok(false);
            }
            app.insert_newline();
        }
        KeyCode::Enter => {
            if app.busy {
                return Ok(false);
            }
            if app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) {
                if app.input.starts_with('/') {
                    let action = app.submit_input();
                    return handle_submit_action(app, backend, action);
                }
            }
            let action = app.submit_input();
            return handle_submit_action(app, backend, action);
        }
        KeyCode::Up if !app.busy && app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) => {
            return Ok(app.select_previous_active_surface_item());
        }
        KeyCode::Down
            if !app.busy && app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) =>
        {
            return Ok(app.select_next_active_surface_item());
        }
        KeyCode::Backspace => app.backspace(),
        KeyCode::Delete => app.delete(),
        KeyCode::Left => app.move_cursor_left(),
        KeyCode::Right => app.move_cursor_right(),
        KeyCode::Home => app.move_cursor_home(),
        KeyCode::End => app.move_cursor_end(),
        KeyCode::Esc => {
            if app.close_active_surface() {
                return Ok(true);
            }
            if !app.input.is_empty() {
                app.clear_input();
            } else if !app.busy {
                app.should_quit = true;
            } else {
                return Ok(false);
            }
        }
        KeyCode::Char('t') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            if !app.busy {
                app.open_transcript_overlay();
            } else {
                return Ok(false);
            }
        }
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.should_quit = true
        }
        KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => app.clear_input(),
        KeyCode::Char(ch) => app.insert_char(ch),
        KeyCode::Tab if !app.busy && app.autocomplete_popup() => {}
        KeyCode::Tab => app.insert_text("    "),
        _ => return Ok(false),
    }

    if !app.busy {
        sync_contextual_popup_data(app);
    }
    Ok(true)
}
