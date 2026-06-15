use ratatui::layout::Rect;
use ratatui::widgets::{Clear, Paragraph};
use unicode_width::UnicodeWidthStr;

use crate::app::{ActiveSurfaceKind, App};
use crate::app_render::truncate_middle;
use crate::bottom_pane::composer::ComposerProps;
use crate::bottom_pane::footer::FooterProps;
use crate::bottom_pane::help_overlay::HelpOverlayProps;
use crate::bottom_pane::picker_overlay::PickerOverlayProps;
use crate::bottom_pane::transcript_overlay::TranscriptOverlayProps;
use crate::custom_terminal::Frame;
use crate::wrap::{wrap_lines, wrapped_height};

pub(crate) fn render_live_region(frame: &mut Frame, area: Rect, app: &App) {
    frame.render_widget(Clear, area);
    let lines = app.rendered_main_lines(area.width.max(1));
    if lines.is_empty() {
        frame.render_widget(Paragraph::new(""), area);
        return;
    }

    let wrapped = wrap_lines(&lines, area.width.max(1));
    let visible = visible_main_region_lines(
        &wrapped,
        area.height,
        app.pending_welcome_banner && !app.busy && !app.has_transcript_lines(),
    );
    frame.render_widget(Paragraph::new(visible), area);
}

fn visible_main_region_lines(
    wrapped: &[ratatui::text::Line<'static>],
    height: u16,
    pin_to_top: bool,
) -> Vec<ratatui::text::Line<'static>> {
    let height = height as usize;
    if wrapped.len() <= height {
        return wrapped.to_vec();
    }
    if pin_to_top {
        wrapped[..height].to_vec()
    } else {
        wrapped[wrapped.len().saturating_sub(height)..].to_vec()
    }
}

pub(crate) fn live_region_height(app: &App, width: u16) -> u16 {
    let lines = app.rendered_main_lines(width.max(1));
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
    let mut parts = vec![app.agent_mode_status_label()];
    if let Some(agent_id) = app.selected_agent_id.as_deref() {
        parts.push(format!("agent {}", truncate_middle(agent_id, 18)));
    }
    if let Some(agent_config) = app.agent_config_path.as_ref() {
        parts.push(format!(
            "config {}",
            truncate_middle(&agent_config.display().to_string(), 24)
        ));
    }
    if let Some(sandbox_type) = app.sandbox_type.as_deref() {
        parts.push(format!("sandbox {sandbox_type}"));
    }
    if let Some(goal) = app.current_goal.as_ref() {
        parts.push(format!("goal {}", goal.status));
    }
    parts.push(compact_workspace_label(&app.workspace_label));
    if app.busy {
        if let Some(phase) = app.active_phase_label() {
            parts.push(format!("phase {phase}"));
        }
    }
    parts.push(normalize_footer_status(&app.footer_status()));
    if app.busy && app.active_tool_status().is_none() {
        parts.push(app.session_label().to_string());
    }
    parts.join(" • ")
}

fn normalize_footer_status(status: &str) -> String {
    status.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn compact_workspace_label(workspace_label: &str) -> String {
    if UnicodeWidthStr::width(workspace_label) <= 26 {
        workspace_label.to_string()
    } else {
        truncate_middle(workspace_label, 26)
    }
}

#[cfg(test)]
mod tests {
    use crate::app::App;
    use crate::wrap::wrap_lines;
    use ratatui::text::Line;

    use super::{footer_status_summary, normalize_footer_status, visible_main_region_lines};

    #[test]
    fn normalize_footer_status_collapses_internal_spacing() {
        assert_eq!(
            normalize_footer_status("ready  local-000001  •  total 1.2s"),
            "ready local-000001 • total 1.2s"
        );
    }

    #[test]
    fn footer_summary_does_not_leak_double_space_statuses() {
        let mut app = App::new();
        app.ensure_local_session();
        app.status = format!("ready  {}", app.session_id);

        let summary = footer_status_summary(&app);

        assert!(summary.contains("ready local-000001"));
        assert!(!summary.contains("ready  local-000001"));
    }

    #[test]
    fn clipped_welcome_region_keeps_header_visible() {
        let app = App::new();
        let lines = app.rendered_main_lines(120);
        let wrapped = wrap_lines(&lines, 120);

        let visible = visible_main_region_lines(&wrapped, 6, true)
            .iter()
            .flat_map(|line| line.spans.iter())
            .map(|span| span.content.as_ref())
            .collect::<Vec<_>>()
            .join("\n");

        assert!(visible.contains("Sage Terminal"));
        assert!(!visible.contains("start: "));
    }

    #[test]
    fn clipped_transcript_region_keeps_latest_output_visible() {
        let wrapped = (0..12)
            .map(|idx| Line::from(format!("line {idx}")))
            .collect::<Vec<_>>();

        let visible = visible_main_region_lines(&wrapped, 6, false)
            .iter()
            .flat_map(|line| line.spans.iter())
            .map(|span| span.content.as_ref())
            .collect::<Vec<_>>()
            .join("\n");

        assert!(visible.contains("line 11"));
        assert!(!visible.contains("line 0"));
    }
}
