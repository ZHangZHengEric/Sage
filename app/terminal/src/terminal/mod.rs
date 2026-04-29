use std::io;
use std::io::ErrorKind;
use std::time::Duration;

use anyhow::Result;
use crossterm::cursor;
use crossterm::event::{
    self, DisableBracketedPaste, EnableBracketedPaste, Event, KeyEventKind,
    KeyboardEnhancementFlags, PopKeyboardEnhancementFlags, PushKeyboardEnhancementFlags,
};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode};
use crossterm::terminal::{Clear, ClearType};

use crate::app::{App, MessageKind, SubmitAction};
use crate::backend::{BackendEvent, BackendHandle, BackendRequest};
use crate::custom_terminal::{BackendImpl, Terminal};
use crate::history::insert_history_lines;
use crate::terminal_layout::desired_viewport_height;
use crate::terminal_support::sync_contextual_popup_data;
use crate::ui;
use crate::wrap::wrap_lines;

mod actions;
mod keys;
#[cfg(test)]
mod tests;

use actions::handle_submit_action;
use keys::handle_key;

pub type AppTerminal = Terminal<BackendImpl>;
const INLINE_VIEWPORT_IDLE_HEIGHT: u16 = 5;
const INLINE_VIEWPORT_MAX_HEIGHT: u16 = 14;
const KEYBOARD_ENHANCEMENT_FLAGS: KeyboardEnhancementFlags =
    KeyboardEnhancementFlags::DISAMBIGUATE_ESCAPE_CODES
        .union(KeyboardEnhancementFlags::REPORT_EVENT_TYPES)
        .union(KeyboardEnhancementFlags::REPORT_ALTERNATE_KEYS)
        .union(KeyboardEnhancementFlags::REPORT_ALL_KEYS_AS_ESCAPE_CODES);

pub fn setup_terminal(_app: &App) -> Result<AppTerminal> {
    let startup_cursor = cursor::position()
        .ok()
        .map(|(x, y)| ratatui::layout::Position { x, y });
    enable_raw_mode()?;
    execute!(io::stdout(), EnableBracketedPaste)?;
    ignore_unsupported(execute!(
        io::stdout(),
        PushKeyboardEnhancementFlags(KEYBOARD_ENHANCEMENT_FLAGS)
    ))?;
    let backend = BackendImpl::new(io::stdout());
    Ok(match startup_cursor {
        Some(position) => Terminal::with_viewport_height_and_cursor(
            backend,
            INLINE_VIEWPORT_IDLE_HEIGHT,
            position,
        )?,
        None => Terminal::with_viewport_height(backend, INLINE_VIEWPORT_IDLE_HEIGHT)?,
    })
}

pub fn restore_terminal(terminal: &mut AppTerminal) -> Result<()> {
    disable_raw_mode()?;
    let viewport = terminal.viewport_area();
    let backend = terminal.backend_mut();
    ignore_unsupported(execute!(
        backend,
        PopKeyboardEnhancementFlags,
        DisableBracketedPaste,
        crossterm::style::ResetColor,
        crossterm::cursor::Show,
        crossterm::cursor::MoveTo(0, viewport.y),
        Clear(ClearType::FromCursorDown),
        crossterm::cursor::MoveTo(0, viewport.y)
    ))?;
    Ok(())
}

pub fn run(terminal: &mut AppTerminal, app: &mut App) -> Result<()> {
    run_with_startup_action(terminal, app, None)
}

pub fn run_with_startup_action(
    terminal: &mut AppTerminal,
    app: &mut App,
    startup_action: Option<SubmitAction>,
) -> Result<()> {
    let mut backend: Option<BackendHandle> = None;
    if let Some(action) = startup_action {
        let _ = handle_submit_action(app, &mut backend, action)?;
    }
    let mut dirty = true;
    let mut viewport_height = terminal.viewport_area().height.max(1);
    let mut last_elapsed_tick: Option<u64> = None;

    loop {
        if app.take_clear_request() {
            terminal.clear()?;
            dirty = true;
        }
        if app.take_backend_restart_request() {
            stop_backend(backend.take());
        }

        let width = terminal.size()?.width.max(1);
        app.materialize_pending_ui(width);
        let elapsed_tick = app.live_elapsed_seconds();
        if elapsed_tick != last_elapsed_tick {
            dirty = true;
            last_elapsed_tick = elapsed_tick;
        }

        let desired_height = desired_viewport_height(
            app,
            width,
            INLINE_VIEWPORT_IDLE_HEIGHT,
            INLINE_VIEWPORT_MAX_HEIGHT,
        );
        if desired_height != viewport_height {
            terminal.set_viewport_height(desired_height)?;
            terminal.clear()?;
            viewport_height = desired_height;
            dirty = true;
        }

        dirty |= drain_backend(app, &mut backend);
        dirty |= flush_history(terminal, app)?;
        if dirty {
            terminal.draw(|frame| ui::render(frame, app))?;
            dirty = false;
        }

        if app.should_quit {
            break;
        }

        if event::poll(Duration::from_millis(16))? {
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    dirty |= handle_key(app, key, &mut backend)?
                }
                Event::Paste(text) => {
                    if !app.is_help_overlay_visible() && !app.is_session_picker_visible() {
                        app.insert_text(&text);
                        sync_contextual_popup_data(app);
                        dirty = true;
                    }
                }
                Event::Resize(_, _) => dirty = true,
                _ => {}
            }
        }
    }

    if let Some(handle) = backend.take() {
        handle.stop();
    }

    Ok(())
}

fn drain_backend(app: &mut App, backend: &mut Option<BackendHandle>) -> bool {
    let mut changed = false;

    if let Some(handle) = backend.as_ref() {
        while let Some(event) = handle.try_next() {
            changed = true;
            match event {
                BackendEvent::LiveChunk(kind, chunk) => match kind {
                    MessageKind::Assistant => app.append_assistant_chunk(&chunk),
                    MessageKind::Process => app.append_process_chunk(&chunk),
                    other => app.push_message(other, chunk),
                },
                BackendEvent::Message(kind, message) => app.push_message(kind, message),
                BackendEvent::Status(status) => app.set_status(status),
                BackendEvent::ToolStarted(name) => app.start_tool(name),
                BackendEvent::ToolFinished(name) => app.finish_tool(name),
                BackendEvent::Error(message) => app.fail_request(message),
                BackendEvent::Finished => {
                    app.complete_request();
                }
                BackendEvent::Exited => {
                    backend.take();
                    break;
                }
            }
        }
    }

    changed
}

fn flush_history(terminal: &mut AppTerminal, app: &mut App) -> Result<bool> {
    let lines = app.take_pending_history_lines();
    if lines.is_empty() {
        return Ok(false);
    }
    let wrapped = wrap_lines(&lines, terminal.size()?.width.max(1));
    insert_history_lines(terminal, &wrapped)?;
    Ok(true)
}

fn ensure_backend<'a>(
    backend: &'a mut Option<BackendHandle>,
    request: &BackendRequest,
) -> Result<&'a BackendHandle> {
    let restart = match backend.as_ref() {
        Some(handle) => !handle.matches(request),
        None => true,
    };
    if restart {
        stop_backend(backend.take());
        *backend = Some(BackendHandle::spawn(request)?);
    }
    Ok(backend.as_ref().expect("backend must exist"))
}

fn stop_backend(handle: Option<BackendHandle>) {
    if let Some(handle) = handle {
        handle.stop();
    }
}

fn ignore_unsupported(result: io::Result<()>) -> io::Result<()> {
    match result {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == ErrorKind::Unsupported => Ok(()),
        Err(err) => Err(err),
    }
}
