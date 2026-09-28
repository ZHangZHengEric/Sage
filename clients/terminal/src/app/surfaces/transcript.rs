use ratatui::text::Line;

use crate::app::{App, TranscriptOverlayState};
use crate::bottom_pane::transcript_overlay;

impl App {
    pub fn open_transcript_overlay(&mut self) {
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.session_picker = None;
        self.transcript_overlay = Some(TranscriptOverlayState { scroll: 0 });
        self.status = format!("transcript  {}", self.session_id);
    }

    pub fn transcript_overlay_props(
        &self,
        viewport_width: u16,
    ) -> Option<transcript_overlay::TranscriptOverlayProps> {
        let overlay = self.transcript_overlay?;
        let lines = self.transcript_lines();
        let line_count = lines.len();
        let max_scroll = max_transcript_scroll_for_lines(&lines, viewport_width);
        let scroll = overlay.scroll.min(max_scroll);
        Some(transcript_overlay::TranscriptOverlayProps {
            title: "Transcript".to_string(),
            lines,
            scroll,
            footer_hint: "↑/↓ scroll • pgup/pgdn jump • esc close".to_string(),
            status: if line_count == 0 {
                "empty transcript".to_string()
            } else {
                format!(
                    "{line_count} committed lines  •  position {}/{}",
                    scroll.saturating_add(1),
                    max_scroll.saturating_add(1)
                )
            },
        })
    }

    pub fn close_transcript_overlay(&mut self) -> bool {
        if self.transcript_overlay.is_none() {
            return false;
        }
        self.transcript_overlay = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }

    pub fn scroll_transcript_overlay_up(&mut self, amount: u16) -> bool {
        let Some(overlay) = self.transcript_overlay.as_mut() else {
            return false;
        };
        let old = overlay.scroll;
        overlay.scroll = overlay.scroll.saturating_sub(amount);
        overlay.scroll != old
    }

    pub fn scroll_transcript_overlay_down(&mut self, amount: u16) -> bool {
        let max_scroll = max_transcript_scroll_for_lines(&self.transcript_lines(), 92);
        let Some(overlay) = self.transcript_overlay.as_mut() else {
            return false;
        };
        let old = overlay.scroll;
        overlay.scroll = overlay.scroll.saturating_add(amount).min(max_scroll);
        overlay.scroll != old
    }

    pub fn page_transcript_overlay_down(&mut self, amount: u16) -> bool {
        self.scroll_transcript_overlay_down(amount.max(4))
    }

    pub fn page_transcript_overlay_up(&mut self, amount: u16) -> bool {
        self.scroll_transcript_overlay_up(amount.max(4))
    }

    fn transcript_lines(&self) -> Vec<Line<'static>> {
        self.committed_history_lines
            .iter()
            .chain(self.pending_history_lines.iter())
            .cloned()
            .collect()
    }
}

fn transcript_body_height(props: &transcript_overlay::TranscriptOverlayProps) -> u16 {
    transcript_overlay::required_height(props).saturating_sub(2)
}

fn max_transcript_scroll_for_lines(lines: &[Line<'static>], viewport_width: u16) -> u16 {
    let props = transcript_overlay::TranscriptOverlayProps {
        title: "Transcript".to_string(),
        lines: lines.to_vec(),
        scroll: 0,
        footer_hint: String::new(),
        status: String::new(),
    };
    let total = transcript_overlay::wrapped_line_count(&props, viewport_width);
    let body = transcript_body_height(&props);
    total.saturating_sub(body)
}
