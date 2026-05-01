use ratatui::layout::Rect;
use ratatui::widgets::{Clear, Paragraph};
use unicode_width::UnicodeWidthStr;

use crate::app::{ActiveSurfaceKind, App};
use crate::app_render::truncate_middle;
use crate::bottom_pane::command_popup;
use crate::bottom_pane::composer::ComposerProps;
use crate::bottom_pane::footer::FooterProps;
use crate::bottom_pane::help_overlay::HelpOverlayProps;
use crate::bottom_pane::picker_overlay::PickerOverlayProps;
use crate::bottom_pane::transcript_overlay::TranscriptOverlayProps;
use crate::custom_terminal::Frame;
use crate::wrap::{wrap_lines, wrapped_height};

pub(crate) fn render_live_region(frame: &mut Frame, area: Rect, app: &App) {
    frame.render_widget(Clear, area);
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

pub(crate) fn live_region_height(app: &App, width: u16) -> u16 {
    let lines = if app.busy {
        app.rendered_live_lines()
    } else {
        app.rendered_idle_lines(width.max(1))
    };
    if lines.is_empty() {
        1
    } else {
        wrapped_height(&lines, width.max(1)).max(1)
    }
}

pub(crate) fn composer_props(app: &App) -> ComposerProps<'_> {
    ComposerProps {
        input: &app.input,
        input_cursor: app.input_cursor,
        busy: app.busy,
    }
}

pub(crate) fn command_popup_height(app: &App) -> u16 {
    command_popup::popup_height(app.popup_props().as_ref())
}

pub(crate) fn help_overlay_props(app: &App) -> Option<HelpOverlayProps> {
    app.help_overlay_props()
}

pub(crate) fn picker_overlay_props(app: &App) -> Option<PickerOverlayProps> {
    app.session_picker_props()
}

pub(crate) fn transcript_overlay_props(app: &App, width: u16) -> Option<TranscriptOverlayProps> {
    app.transcript_overlay_props(width)
}

pub(crate) fn footer_props(app: &App) -> FooterProps {
    FooterProps {
        left_hint: footer_hint(app),
        right_summary: footer_status_summary(app),
    }
}

pub(crate) fn footer_hint(app: &App) -> String {
    match app.active_surface_kind() {
        Some(ActiveSurfaceKind::Help) => {
            "esc/enter close  •  /help <command> for details".to_string()
        }
        Some(ActiveSurfaceKind::SessionPicker) => {
            "type filter  •  ↑/↓ pick  •  enter open  •  esc close".to_string()
        }
        Some(ActiveSurfaceKind::Transcript) => {
            "↑/↓ scroll  •  pgup/pgdn jump  •  esc close".to_string()
        }
        Some(ActiveSurfaceKind::Popup) => {
            "↑/↓ select  •  tab complete  •  esc close  •  enter apply".to_string()
        }
        None if app.busy => match app.active_tool_status() {
            Some(tool) => format!("running {tool}"),
            None => match app.active_phase_label() {
                Some(phase) => format!("{phase}... output is streaming"),
                None => "working... output is streaming".to_string(),
            },
        },
        None => "shift+enter newline  •  /help commands  •  enter send".to_string(),
    }
}

pub(crate) fn footer_status_summary(app: &App) -> String {
    let mut parts = vec![app.agent_mode.clone()];
    if let Some(agent_id) = app.selected_agent_id.as_deref() {
        parts.push(format!("agent {}", truncate_middle(agent_id, 18)));
    }
    parts.push(compact_workspace_label(&app.workspace_label));
    if app.busy {
        if let Some(phase) = app.active_phase_label() {
            parts.push(format!("phase {phase}"));
        }
    }
    parts.push(normalize_footer_status(&app.footer_status()));
    if app.busy && app.active_tool_status().is_none() {
        parts.push(app.session_id.clone());
    }
    parts.join(" • ")
}

fn normalize_footer_status(status: &str) -> String {
    status.replace("  •  ", " • ")
}

fn compact_workspace_label(workspace_label: &str) -> String {
    if UnicodeWidthStr::width(workspace_label) <= 26 {
        workspace_label.to_string()
    } else {
        truncate_middle(workspace_label, 26)
    }
}
