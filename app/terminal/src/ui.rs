use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::widgets::Paragraph;

use crate::app::{ActiveSurfaceKind, App};
use crate::bottom_pane::command_popup;
use crate::bottom_pane::composer::ComposerProps;
use crate::bottom_pane::footer::FooterProps;
use crate::bottom_pane::help_overlay::HelpOverlayProps;
use crate::bottom_pane::picker_overlay::PickerOverlayProps;
use crate::bottom_pane::transcript_overlay::TranscriptOverlayProps;
use crate::bottom_pane::{composer, footer, help_overlay, picker_overlay, transcript_overlay};
use crate::custom_terminal::Frame;
use crate::wrap::wrap_lines;

pub fn render(frame: &mut Frame, app: &App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(1),
            Constraint::Length(3),
            Constraint::Length(command_popup_height(app)),
            Constraint::Length(1),
        ])
        .split(frame.area());

    render_live_region(frame, chunks[0], app);
    let composer_props = composer_props(app);
    if let Some(cursor) = composer::render(frame, chunks[1], &composer_props) {
        frame.set_cursor_position(cursor);
    }
    if let Some(popup_props) = app.popup_props() {
        command_popup::render(frame, chunks[2], &popup_props);
    }
    let footer_props = footer_props(app);
    footer::render(frame, chunks[3], &footer_props);
    match app.active_surface_kind() {
        Some(ActiveSurfaceKind::Help) => {
            if let Some(props) = help_overlay_props(app) {
                help_overlay::render(frame, &props);
            }
        }
        Some(ActiveSurfaceKind::SessionPicker) => {
            if let Some(props) = picker_overlay_props(app) {
                picker_overlay::render(frame, &props);
            }
        }
        Some(ActiveSurfaceKind::Transcript) => {
            if let Some(props) = transcript_overlay_props(app, frame.area().width) {
                transcript_overlay::render(frame, &props);
            }
        }
        _ => {}
    }
}

fn render_live_region(frame: &mut Frame, area: ratatui::layout::Rect, app: &App) {
    let lines = if app.busy {
        app.rendered_live_lines()
    } else {
        app.rendered_idle_lines(area.width.max(1))
    };
    if lines.is_empty() {
        frame.render_widget(Paragraph::new(""), area);
        return;
    }

    frame.render_widget(Paragraph::new(wrap_lines(&lines, area.width.max(1))), area);
}

fn composer_props(app: &App) -> ComposerProps<'_> {
    ComposerProps {
        input: &app.input,
        input_cursor: app.input_cursor,
        busy: app.busy,
    }
}

fn command_popup_height(app: &App) -> u16 {
    command_popup::popup_height(app.popup_props().as_ref())
}

fn help_overlay_props(app: &App) -> Option<HelpOverlayProps> {
    app.help_overlay_props()
}

fn picker_overlay_props(app: &App) -> Option<PickerOverlayProps> {
    app.session_picker_props()
}

fn transcript_overlay_props(app: &App, width: u16) -> Option<TranscriptOverlayProps> {
    app.transcript_overlay_props(width)
}

fn footer_props(app: &App) -> FooterProps {
    FooterProps {
        left_hint: footer_hint(app),
        right_summary: footer_status_summary(app),
    }
}

fn footer_hint(app: &App) -> String {
    match app.active_surface_kind() {
        Some(ActiveSurfaceKind::Help) => "esc/enter close help".to_string(),
        Some(ActiveSurfaceKind::SessionPicker) => {
            "type filter  •  ↑/↓ pick session  •  esc close".to_string()
        }
        Some(ActiveSurfaceKind::Transcript) => {
            "↑/↓ scroll  •  pgup/pgdn jump  •  esc close".to_string()
        }
        Some(ActiveSurfaceKind::Popup) => {
            "↑/↓ select  •  tab complete  •  esc close  •  enter apply".to_string()
        }
        None if app.busy => match app.active_tool_status() {
            Some(tool) => format!("running {tool}"),
            None => "working... output is streaming".to_string(),
        },
        None => "esc quit  •  /help commands  •  enter send".to_string(),
    }
}

fn footer_status_summary(app: &App) -> String {
    let mut parts = vec![
        app.agent_mode.clone(),
        app.workspace_label.clone(),
        normalize_footer_status(&app.footer_status()),
    ];
    if app.busy && app.active_tool_status().is_none() {
        parts.push(app.session_id.clone());
    }
    parts.join(" • ")
}

fn normalize_footer_status(status: &str) -> String {
    status.replace("  •  ", " • ")
}
