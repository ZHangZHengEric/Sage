mod diff;
mod draw;

use std::fmt;
use std::io;
use std::io::Write;

use crossterm::queue;
use crossterm::style::{Attribute as CAttribute, ResetColor, SetAttribute};
use crossterm::terminal::ScrollUp;
use ratatui::backend::{Backend, CrosstermBackend};
use ratatui::buffer::Buffer;
use ratatui::layout::{Position, Rect, Size};
use ratatui::widgets::Widget;

use self::diff::{diff_buffers, viewport_rect};
use self::draw::draw_commands;

pub type BackendImpl = CrosstermBackend<std::io::Stdout>;

pub struct Frame<'a> {
    cursor_position: Option<Position>,
    viewport_area: Rect,
    buffer: &'a mut Buffer,
}

impl Frame<'_> {
    pub const fn area(&self) -> Rect {
        self.viewport_area
    }

    pub fn render_widget<W: Widget>(&mut self, widget: W, area: Rect) {
        widget.render(area, self.buffer);
    }

    pub fn set_cursor_position<P: Into<Position>>(&mut self, position: P) {
        self.cursor_position = Some(position.into());
    }
}

pub struct Terminal<B>
where
    B: Backend + Write,
{
    backend: B,
    buffers: [Buffer; 2],
    current: usize,
    hidden_cursor: bool,
    viewport_area: Rect,
    viewport_height: u16,
    last_known_screen_size: Size,
    last_known_cursor_pos: Position,
    visible_history_rows: u16,
}

impl<B> Drop for Terminal<B>
where
    B: Backend + Write,
{
    fn drop(&mut self) {
        let _ = self.show_cursor();
    }
}

impl<B> Terminal<B>
where
    B: Backend + Write,
{
    pub fn with_viewport_height_and_cursor(
        backend: B,
        viewport_height: u16,
        cursor_pos: Position,
    ) -> io::Result<Self> {
        let screen_size = backend.size()?;
        let viewport_area = viewport_rect(screen_size, viewport_height, cursor_pos.y);
        Ok(Self {
            backend,
            buffers: [Buffer::empty(viewport_area), Buffer::empty(viewport_area)],
            current: 0,
            hidden_cursor: false,
            viewport_area,
            viewport_height: viewport_height.max(1),
            last_known_screen_size: screen_size,
            last_known_cursor_pos: cursor_pos,
            visible_history_rows: cursor_pos.y,
        })
    }

    pub fn draw<F>(&mut self, render_callback: F) -> io::Result<()>
    where
        F: FnOnce(&mut Frame),
    {
        self.autoresize()?;

        let cursor_position = {
            let mut frame = Frame {
                cursor_position: None,
                viewport_area: self.viewport_area,
                buffer: self.current_buffer_mut(),
            };
            render_callback(&mut frame);
            frame.cursor_position
        };

        self.flush()?;
        match cursor_position {
            Some(position) => {
                self.show_cursor()?;
                self.set_cursor_position(position)?;
            }
            None => self.hide_cursor()?,
        }

        self.swap_buffers();
        Backend::flush(&mut self.backend)?;
        Ok(())
    }

    pub fn size(&self) -> io::Result<Size> {
        self.backend.size()
    }

    pub fn clear(&mut self) -> io::Result<()> {
        self.clear_after_position(self.viewport_area.as_position())
    }

    pub fn clear_viewport_for_exit(&mut self) -> io::Result<()> {
        queue!(self.backend, ResetColor, SetAttribute(CAttribute::Reset))?;
        self.clear_after_position(self.viewport_area.as_position())?;
        Backend::flush(&mut self.backend)?;
        Ok(())
    }

    pub fn clear_after_position(&mut self, position: Position) -> io::Result<()> {
        self.backend.set_cursor_position(position)?;
        self.backend
            .clear_region(ratatui::backend::ClearType::AfterCursor)?;
        self.previous_buffer_mut().reset();
        Ok(())
    }

    pub fn backend_mut(&mut self) -> &mut B {
        &mut self.backend
    }

    pub fn viewport_area(&self) -> Rect {
        self.viewport_area
    }

    pub fn last_known_cursor_pos(&self) -> Position {
        self.last_known_cursor_pos
    }

    pub fn invalidate_viewport(&mut self) {
        self.previous_buffer_mut().reset();
    }

    pub fn set_viewport_area(&mut self, area: Rect) {
        self.viewport_area = area;
        self.visible_history_rows = self.visible_history_rows.min(area.top());
        self.current_buffer_mut().resize(area);
        self.previous_buffer_mut().resize(area);
        self.current_buffer_mut().reset();
        self.previous_buffer_mut().reset();
    }

    pub fn set_viewport_height(&mut self, viewport_height: u16) -> io::Result<()> {
        self.viewport_height = viewport_height.max(1);
        let size = self.size()?;
        self.last_known_screen_size = size;
        let mut next_area = self.viewport_area;
        next_area.width = size.width;
        next_area.height = self.viewport_height.min(size.height.max(1));

        let history_anchor = self.visible_history_rows.min(size.height.saturating_sub(1));
        if history_anchor > 0 || self.viewport_area.y <= history_anchor {
            next_area.y = history_anchor.min(size.height.saturating_sub(next_area.height));
            if next_area.bottom() > size.height {
                let overflow = next_area.bottom().saturating_sub(size.height);
                scroll_region_up(&mut self.backend, 0..next_area.y, overflow)?;
                next_area.y = size.height.saturating_sub(next_area.height);
                self.visible_history_rows = self.visible_history_rows.saturating_sub(overflow);
            }
        } else {
            next_area = viewport_rect(size, self.viewport_height, self.viewport_area.y);
        }
        if next_area != self.viewport_area {
            if next_area.height > self.viewport_area.height && next_area.y < self.viewport_area.y {
                scroll_region_up(
                    &mut self.backend,
                    0..self.viewport_area.y,
                    self.viewport_area.y.saturating_sub(next_area.y),
                )?;
            }
            let clear_y = self.viewport_area.y.min(next_area.y);
            self.clear_after_position(Position { x: 0, y: clear_y })?;
        }
        self.set_viewport_area(next_area);
        self.previous_buffer_mut().reset();
        Ok(())
    }

    pub fn note_history_rows_inserted(&mut self, rows: u16) {
        self.visible_history_rows = self
            .visible_history_rows
            .saturating_add(rows)
            .min(self.viewport_area.top());
    }

    pub fn set_cursor_position<P: Into<Position>>(&mut self, position: P) -> io::Result<()> {
        let position = position.into();
        self.backend.set_cursor_position(position)?;
        self.last_known_cursor_pos = position;
        Ok(())
    }

    pub fn hide_cursor(&mut self) -> io::Result<()> {
        self.backend.hide_cursor()?;
        self.hidden_cursor = true;
        Ok(())
    }

    pub fn show_cursor(&mut self) -> io::Result<()> {
        self.backend.show_cursor()?;
        self.hidden_cursor = false;
        Ok(())
    }

    fn autoresize(&mut self) -> io::Result<()> {
        let size = self.size()?;
        if size != self.last_known_screen_size {
            self.last_known_screen_size = size;
            self.set_viewport_area(viewport_rect(
                size,
                self.viewport_height,
                self.viewport_area.y,
            ));
            self.previous_buffer_mut().reset();
        }
        Ok(())
    }

    fn flush(&mut self) -> io::Result<()> {
        let updates = diff_buffers(self.previous_buffer(), self.current_buffer());
        if let Some((x, y)) = updates.iter().rev().find_map(|command| match command {
            diff::DrawCommand::Put { x, y, .. } => Some((*x, *y)),
            diff::DrawCommand::ClearToEnd { .. } => None,
        }) {
            self.last_known_cursor_pos = Position { x, y };
        }
        draw_commands(&mut self.backend, updates.into_iter())
    }

    fn current_buffer(&self) -> &Buffer {
        &self.buffers[self.current]
    }

    fn current_buffer_mut(&mut self) -> &mut Buffer {
        &mut self.buffers[self.current]
    }

    fn previous_buffer(&self) -> &Buffer {
        &self.buffers[1 - self.current]
    }

    fn previous_buffer_mut(&mut self) -> &mut Buffer {
        &mut self.buffers[1 - self.current]
    }

    fn swap_buffers(&mut self) {
        self.previous_buffer_mut().reset();
        self.current = 1 - self.current;
    }
}

fn scroll_region_up<W: Write>(
    writer: &mut W,
    region: std::ops::Range<u16>,
    amount: u16,
) -> io::Result<()> {
    if amount == 0 || region.is_empty() {
        return Ok(());
    }
    queue!(
        writer,
        SetScrollRegion(region.start.saturating_add(1)..region.end),
        ScrollUp(amount),
        ResetScrollRegion
    )?;
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SetScrollRegion(std::ops::Range<u16>);

impl crossterm::Command for SetScrollRegion {
    fn write_ansi(&self, f: &mut impl fmt::Write) -> fmt::Result {
        write!(f, "\x1b[{};{}r", self.0.start, self.0.end)
    }

    #[cfg(windows)]
    fn execute_winapi(&self) -> io::Result<()> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "SetScrollRegion requires ANSI terminal support",
        ))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ResetScrollRegion;

impl crossterm::Command for ResetScrollRegion {
    fn write_ansi(&self, f: &mut impl fmt::Write) -> fmt::Result {
        write!(f, "\x1b[r")
    }

    #[cfg(windows)]
    fn execute_winapi(&self) -> io::Result<()> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "ResetScrollRegion requires ANSI terminal support",
        ))
    }
}

#[cfg(test)]
mod tests {
    use std::io;
    use std::io::Write;

    use ratatui::backend::{Backend, ClearType, WindowSize};
    use ratatui::buffer::Cell;
    use ratatui::layout::{Position, Size};

    use super::Terminal;

    #[derive(Default)]
    struct RecordingBackend {
        out: Vec<u8>,
        size: Size,
        cursor: Position,
        clear_region: Option<ClearType>,
        flushed: bool,
    }

    impl RecordingBackend {
        fn new(width: u16, height: u16) -> Self {
            Self {
                size: Size { width, height },
                ..Self::default()
            }
        }
    }

    impl Write for RecordingBackend {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.out.extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            self.flushed = true;
            Ok(())
        }
    }

    impl Backend for RecordingBackend {
        fn draw<'a, I>(&mut self, _content: I) -> io::Result<()>
        where
            I: Iterator<Item = (u16, u16, &'a Cell)>,
        {
            Ok(())
        }

        fn hide_cursor(&mut self) -> io::Result<()> {
            Ok(())
        }

        fn show_cursor(&mut self) -> io::Result<()> {
            Ok(())
        }

        fn get_cursor_position(&mut self) -> io::Result<Position> {
            Ok(self.cursor)
        }

        fn set_cursor_position<P: Into<Position>>(&mut self, position: P) -> io::Result<()> {
            self.cursor = position.into();
            Ok(())
        }

        fn clear(&mut self) -> io::Result<()> {
            self.clear_region = Some(ClearType::All);
            Ok(())
        }

        fn clear_region(&mut self, clear_type: ClearType) -> io::Result<()> {
            self.clear_region = Some(clear_type);
            Ok(())
        }

        fn size(&self) -> io::Result<Size> {
            Ok(self.size)
        }

        fn window_size(&mut self) -> io::Result<WindowSize> {
            Ok(WindowSize {
                columns_rows: self.size,
                pixels: Size::default(),
            })
        }

        fn flush(&mut self) -> io::Result<()> {
            Write::flush(self)
        }
    }

    #[test]
    fn clear_viewport_for_exit_resets_style_and_clears_from_viewport_top() {
        let backend = RecordingBackend::new(80, 24);
        let mut terminal =
            Terminal::with_viewport_height_and_cursor(backend, 5, Position { x: 0, y: 10 })
                .expect("terminal");

        terminal.clear_viewport_for_exit().expect("clear exit");

        let backend = terminal.backend_mut();
        let rendered = String::from_utf8_lossy(&backend.out);
        assert!(
            rendered.contains("\x1b[0m"),
            "exit cleanup should reset attributes before clearing: {rendered:?}"
        );
        assert_eq!(backend.cursor, Position { x: 0, y: 10 });
        assert_eq!(backend.clear_region, Some(ClearType::AfterCursor));
        assert!(backend.flushed);
    }
}
