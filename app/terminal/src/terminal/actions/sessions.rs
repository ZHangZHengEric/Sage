use anyhow::Result;

use crate::app::{App, MessageKind, SessionPickerEntry, SessionPickerMode};
use crate::backend::{inspect_latest_session, inspect_session, list_sessions};
use crate::terminal_support::{apply_resumed_session, format_session_detail};

pub(super) fn open_session_picker(
    app: &mut App,
    mode: SessionPickerMode,
    limit: usize,
) -> Result<bool> {
    match list_sessions(&app.user_id, limit) {
        Ok(sessions) if sessions.is_empty() => {
            app.push_message(
                MessageKind::System,
                "No saved sessions available.\n\nStart a conversation and use /resume or /sessions later.",
            );
            app.set_status(format!("resume unavailable  {}", app.session_id));
        }
        Ok(sessions) => {
            app.open_session_picker(
                mode,
                sessions
                    .into_iter()
                    .map(|session| SessionPickerEntry {
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

pub(super) fn resume_latest(app: &mut App) -> Result<bool> {
    match inspect_latest_session(&app.user_id) {
        Ok(Some(detail)) => apply_resumed_session(app, detail),
        Ok(None) => {
            app.push_message(
                MessageKind::System,
                "No saved sessions available.\n\nStart a conversation and try again later.",
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

pub(super) fn resume_session(app: &mut App, session_id: &str) -> Result<bool> {
    match inspect_session(session_id, &app.user_id) {
        Ok(Some(detail)) => apply_resumed_session(app, detail),
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

pub(super) fn show_session(app: &mut App, session_id: &str) -> Result<bool> {
    let detail = if session_id == "latest" {
        inspect_latest_session(&app.user_id)
    } else {
        inspect_session(session_id, &app.user_id)
    };

    match detail {
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
