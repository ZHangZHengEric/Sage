mod diff;
mod draw;

use std::io;
use std::io::Write;

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
    pub fn with_viewport_height(mut backend: B, viewport_height: u16) -> io::Result<Self> {
        let cursor_pos = backend
            .get_cursor_position()
            .unwrap_or(Position { x: 0, y: 0 });
        Self::with_viewport_height_and_cursor(backend, viewport_height, cursor_pos)
    }

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
        self.backend
            .set_cursor_position(self.viewport_area.as_position())?;
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

    pub fn set_viewport_area(&mut self, area: Rect) {
        self.viewport_area = area;
        self.current_buffer_mut().resize(area);
        self.previous_buffer_mut().resize(area);
        self.current_buffer_mut().reset();
        self.previous_buffer_mut().reset();
    }

    pub fn set_viewport_height(&mut self, viewport_height: u16) -> io::Result<()> {
        self.viewport_height = viewport_height.max(1);
        let size = self.size()?;
        self.last_known_screen_size = size;
        self.set_viewport_area(viewport_rect(
            size,
            self.viewport_height,
            self.viewport_area.y,
        ));
        self.previous_buffer_mut().reset();
        Ok(())
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
