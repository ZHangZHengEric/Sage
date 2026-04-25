use std::io;
use std::time::Duration;

use anyhow::Result;
use crossterm::cursor;
use crossterm::event::{
    self, DisableBracketedPaste, EnableBracketedPaste, Event, KeyCode, KeyEvent, KeyEventKind,
    KeyModifiers,
};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode};
use crossterm::terminal::{Clear, ClearType};

use crate::app::{ActiveSurfaceKind, App, MessageKind, SubmitAction};
use crate::backend::{
    create_provider, delete_provider, inspect_latest_session, inspect_provider, inspect_session,
    list_providers, list_sessions, list_skills, read_config, set_default_provider, update_provider,
    BackendEvent, BackendHandle, BackendRequest,
};
use crate::custom_terminal::{BackendImpl, Terminal};
use crate::history::insert_history_lines;
use crate::terminal_layout::desired_viewport_height;
use crate::terminal_support::{
    apply_resumed_session, format_config, format_provider_detail, format_providers,
    format_session_detail, format_skills_list, parse_provider_mutation, repo_root,
    sync_contextual_popup_data,
};
use crate::ui;
use crate::wrap::wrap_lines;

pub type AppTerminal = Terminal<BackendImpl>;
const INLINE_VIEWPORT_IDLE_HEIGHT: u16 = 5;
const INLINE_VIEWPORT_MAX_HEIGHT: u16 = 14;

pub fn setup_terminal(_app: &App) -> Result<AppTerminal> {
    let startup_cursor = cursor::position()
        .ok()
        .map(|(x, y)| ratatui::layout::Position { x, y });
    enable_raw_mode()?;
    execute!(io::stdout(), EnableBracketedPaste)?;
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
    execute!(
        backend,
        DisableBracketedPaste,
        crossterm::style::ResetColor,
        crossterm::cursor::Show,
        crossterm::cursor::MoveTo(0, viewport.y),
        Clear(ClearType::FromCursorDown),
        crossterm::cursor::MoveTo(0, viewport.y)
    )?;
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

fn handle_key(app: &mut App, key: KeyEvent, backend: &mut Option<BackendHandle>) -> Result<bool> {
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
                return Ok(app.clear_session_picker_filter())
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
        KeyCode::Enter => {
            if app.busy {
                return Ok(false);
            }
            if app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) {
                if let Some(action) = app.submit_active_surface() {
                    return handle_submit_action(app, backend, action);
                }
            }
            let action = app.submit_input();
            return handle_submit_action(app, backend, action);
        }
        KeyCode::Up if !app.busy && app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) => {
            return Ok(app.select_previous_active_surface_item())
        }
        KeyCode::Down
            if !app.busy && app.active_surface_kind() == Some(ActiveSurfaceKind::Popup) =>
        {
            return Ok(app.select_next_active_surface_item())
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

fn handle_submit_action(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    action: SubmitAction,
) -> Result<bool> {
    match action {
        SubmitAction::Noop => Ok(false),
        SubmitAction::Handled => Ok(true),
        SubmitAction::RunTask(task) => {
            let request = BackendRequest {
                session_id: app.session_id.clone(),
                user_id: app.user_id.clone(),
                agent_mode: app.agent_mode.clone(),
                max_loop_count: app.max_loop_count,
                workspace: Some(repo_root()),
                skills: app.selected_skills.clone(),
                model_override: app.selected_model.clone(),
                task,
            };
            let handle = ensure_backend(backend, &request)?;
            handle.send_prompt(&request.task)?;
            Ok(true)
        }
        SubmitAction::OpenSessionPicker { mode, limit } => {
            match list_sessions(&app.user_id, limit) {
                Ok(sessions) if sessions.is_empty() => {
                    app.push_message(MessageKind::System, "no saved sessions available");
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Ok(sessions) => {
                    app.open_session_picker(
                        mode,
                        sessions
                            .into_iter()
                            .map(|session| crate::app::SessionPickerEntry {
                                session_id: session.session_id,
                                title: session.title,
                                message_count: session.message_count,
                                updated_at: session.updated_at,
                                preview: session.last_preview,
                            })
                            .collect(),
                    );
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to load sessions: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ListSkills => {
            match list_skills(&app.user_id, Some(repo_root().as_path())) {
                Ok(skills) => {
                    app.set_skill_catalog(
                        skills
                            .iter()
                            .map(|skill| {
                                (
                                    skill.name.clone(),
                                    skill.description.clone(),
                                    skill.source.clone(),
                                )
                            })
                            .collect(),
                    );
                    app.push_message(
                        MessageKind::Tool,
                        format_skills_list(&skills, &app.selected_skills),
                    );
                    app.set_status(format!("skills  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to list skills: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::EnableSkill(skill) => {
            match list_skills(&app.user_id, Some(repo_root().as_path())) {
                Ok(skills) => {
                    app.set_skill_catalog(
                        skills
                            .iter()
                            .map(|skill| {
                                (
                                    skill.name.clone(),
                                    skill.description.clone(),
                                    skill.source.clone(),
                                )
                            })
                            .collect(),
                    );
                    if skills.iter().any(|item| item.name == skill) {
                        app.enable_skill(skill);
                    } else {
                        app.push_message(
                            MessageKind::System,
                            format!(
                                "unknown skill: {skill}\nRun /skills to inspect visible skills."
                            ),
                        );
                        app.set_status(format!("skills  {}", app.session_id));
                    }
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to validate skill: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::DisableSkill(skill) => {
            app.disable_skill(&skill);
            Ok(true)
        }
        SubmitAction::ClearSkills => {
            app.clear_skills();
            Ok(true)
        }
        SubmitAction::ShowConfig => {
            match read_config() {
                Ok(config) => {
                    app.push_message(
                        MessageKind::Tool,
                        format_config(&config, &app.selected_model),
                    );
                    app.set_status(format!("config  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to read config: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ListProviders => {
            match list_providers(&app.user_id) {
                Ok(providers) => {
                    app.set_provider_catalog(
                        providers
                            .iter()
                            .map(|provider| {
                                (
                                    provider.id.clone(),
                                    provider.name.clone(),
                                    provider.model.clone(),
                                    provider.base_url.clone(),
                                    provider.is_default,
                                )
                            })
                            .collect(),
                    );
                    app.push_message(MessageKind::Tool, format_providers(&providers));
                    app.set_status(format!("providers  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to list providers: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowProvider(provider_id) => {
            match inspect_provider(&app.user_id, &provider_id) {
                Ok(provider) => {
                    app.push_message(MessageKind::Tool, format_provider_detail(&provider));
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to inspect provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::SetDefaultProvider(provider_id) => {
            match set_default_provider(&app.user_id, &provider_id) {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!(
                            "default provider set\n{}",
                            format_provider_detail(&provider)
                        ),
                    );
                    if !provider.model.is_empty() {
                        app.selected_model = None;
                    }
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to update provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::CreateProvider(fields) => {
            match parse_provider_mutation(&fields, true)
                .and_then(|mutation| create_provider(&app.user_id, &mutation))
            {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider created\n{}", format_provider_detail(&provider)),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to create provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::UpdateProvider {
            provider_id,
            fields,
        } => {
            match parse_provider_mutation(&fields, false)
                .and_then(|mutation| update_provider(&app.user_id, &provider_id, &mutation))
            {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider updated\n{}", format_provider_detail(&provider)),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to update provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::DeleteProvider(provider_id) => {
            match delete_provider(&app.user_id, &provider_id) {
                Ok(()) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider deleted: {}", provider_id),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to delete provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowModel => {
            match read_config() {
                Ok(config) => {
                    let effective = app
                        .selected_model
                        .clone()
                        .unwrap_or_else(|| config.default_model_name.clone());
                    let source = if app.selected_model.is_some() {
                        "session override"
                    } else {
                        "CLI default"
                    };
                    app.push_message(
                        MessageKind::Tool,
                        format!(
                            "current model: {}\nsource: {}\ndefault model: {}",
                            effective, source, config.default_model_name
                        ),
                    );
                    app.set_status(format!("model  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to read config: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::SetModel(model) => {
            app.set_model_override(model);
            Ok(true)
        }
        SubmitAction::ClearModel => {
            app.clear_model_override();
            Ok(true)
        }
        SubmitAction::ResumeLatest => {
            match inspect_latest_session(&app.user_id) {
                Ok(Some(detail)) => {
                    apply_resumed_session(app, detail);
                }
                Ok(None) => {
                    app.push_message(MessageKind::System, "no saved sessions available");
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to resume: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ResumeSession(session_id) => {
            match inspect_session(&session_id, &app.user_id) {
                Ok(Some(detail)) => {
                    apply_resumed_session(app, detail);
                }
                Ok(None) => {
                    app.push_message(
                        MessageKind::System,
                        format!("session not found: {session_id}"),
                    );
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to resume: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowSession(session_id) => {
            match inspect_session(&session_id, &app.user_id) {
                Ok(Some(detail)) => {
                    app.push_message(MessageKind::Tool, format_session_detail(&detail));
                    app.set_status(format!("session  {}", app.session_id));
                }
                Ok(None) => {
                    app.push_message(
                        MessageKind::System,
                        format!("session not found: {session_id}"),
                    );
                    app.set_status(format!("session unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to inspect session: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
    }
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

#[cfg(test)]
mod tests {
    use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

    use crate::app::{ActiveSurfaceKind, App, MessageKind, SubmitAction};
    use crate::terminal_layout::desired_viewport_height;
    use crate::terminal_support::parse_provider_mutation;

    use super::{handle_key, INLINE_VIEWPORT_IDLE_HEIGHT, INLINE_VIEWPORT_MAX_HEIGHT};

    #[test]
    fn parse_provider_mutation_rejects_invalid_default_flag() {
        let err = parse_provider_mutation(&[String::from("default=maybe")], false)
            .expect_err("default=maybe should fail");
        assert_eq!(
            err.to_string(),
            "invalid default value `maybe`; use true/false, yes/no, on/off, or 1/0"
        );
    }

    #[test]
    fn parse_provider_mutation_rejects_duplicate_fields() {
        let err = parse_provider_mutation(
            &[String::from("model=alpha"), String::from("model=beta")],
            false,
        )
        .expect_err("duplicate model should fail");
        assert_eq!(
            err.to_string(),
            "duplicate provider field `model`; supply it once"
        );
    }

    #[test]
    fn parse_provider_mutation_rejects_empty_values() {
        let err = parse_provider_mutation(&[String::from("name=")], false)
            .expect_err("empty values should fail");
        assert_eq!(err.to_string(), "provider field `name` cannot be empty");
    }

    #[test]
    fn parse_provider_mutation_reports_missing_create_fields() {
        let err = parse_provider_mutation(
            &[
                String::from("name=demo"),
                String::from("base=https://example.com"),
            ],
            true,
        )
        .expect_err("missing model should fail");
        assert_eq!(
            err.to_string(),
            "provider create requires name=..., model=..., base=...; missing: model"
        );
    }

    #[test]
    fn parse_provider_mutation_accepts_false_default_values() {
        let mutation = parse_provider_mutation(
            &[
                String::from("name=demo"),
                String::from("model=demo-chat"),
                String::from("base=https://example.com"),
                String::from("default=off"),
            ],
            true,
        )
        .expect("valid mutation should parse");
        assert_eq!(mutation.is_default, Some(false));
    }

    #[test]
    fn help_overlay_consumes_typing_without_mutating_input() {
        let mut app = App::new();
        app.input = "/help".to_string();
        app.input_cursor = app.input.len();
        assert!(matches!(app.submit_input(), SubmitAction::Handled));

        let mut backend = None;
        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Char('x'), KeyModifiers::NONE),
            &mut backend,
        )
        .expect("typing while help is open should not fail");

        assert!(handled);
        assert!(app.help_overlay_props().is_some());
        assert!(app.input.is_empty());
    }

    #[test]
    fn help_overlay_enter_closes_modal() {
        let mut app = App::new();
        app.input = "/help".to_string();
        app.input_cursor = app.input.len();
        assert!(matches!(app.submit_input(), SubmitAction::Handled));

        let mut backend = None;
        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("enter while help is open should not fail");

        assert!(handled);
        assert!(app.help_overlay_props().is_none());
    }

    #[test]
    fn welcome_banner_expands_idle_viewport_height() {
        let app = App::new();

        assert!(
            desired_viewport_height(
                &app,
                120,
                INLINE_VIEWPORT_IDLE_HEIGHT,
                INLINE_VIEWPORT_MAX_HEIGHT
            ) > INLINE_VIEWPORT_IDLE_HEIGHT
        );
    }

    #[test]
    fn esc_quits_when_idle_and_input_is_empty() {
        let mut app = App::new();
        let mut backend = None;

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("esc should not fail");

        assert!(handled);
        assert!(app.should_quit);
    }

    #[test]
    fn esc_clears_input_before_quitting() {
        let mut app = App::new();
        app.input = "draft".to_string();
        app.input_cursor = app.input.len();
        let mut backend = None;

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("esc should not fail");

        assert!(handled);
        assert!(app.input.is_empty());
        assert!(!app.should_quit);
    }

    #[test]
    fn esc_closes_popup_before_quitting() {
        let mut app = App::new();
        app.input = "/pro".to_string();
        app.input_cursor = app.input.len();
        let mut backend = None;

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("esc should not fail");

        assert!(handled);
        assert!(app.input.is_empty());
        assert!(!app.should_quit);
    }

    #[test]
    fn help_popup_submit_escape_and_welcome_flow_stays_consistent() {
        let mut app = App::new();
        let mut backend = None;

        app.input = "/he".to_string();
        app.input_cursor = app.input.len();
        assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Popup));

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("popup submit should not fail");
        assert!(handled);
        assert!(app.help_overlay_props().is_some());

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
            &mut backend,
        )
        .expect("help escape should not fail");
        assert!(handled);
        assert!(app.help_overlay_props().is_none());

        app.input = "hello".to_string();
        app.input_cursor = app.input.len();
        let action = app.submit_input();
        assert!(matches!(action, SubmitAction::RunTask(_)));
        app.materialize_pending_ui(120);
        let rendered = app
            .pending_history_lines
            .iter()
            .flat_map(|line| line.spans.iter())
            .map(|span| span.content.as_ref())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(rendered.contains("Sage Terminal"));
        assert!(rendered.contains("hello"));
    }

    #[test]
    fn ctrl_t_opens_transcript_overlay_when_idle() {
        let mut app = App::new();
        app.push_message(MessageKind::User, "hello");
        let _ = app.take_pending_history_lines();
        let mut backend = None;

        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Char('t'), KeyModifiers::CONTROL),
            &mut backend,
        )
        .expect("ctrl-t should not fail");

        assert!(handled);
        assert_eq!(
            app.active_surface_kind(),
            Some(ActiveSurfaceKind::Transcript)
        );
    }
}
