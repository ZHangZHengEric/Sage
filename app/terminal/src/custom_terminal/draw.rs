use std::io;
use std::io::Write;

use crossterm::cursor::MoveTo;
use crossterm::queue;
use crossterm::style::{
    Attribute as CAttribute, Print, SetAttribute, SetBackgroundColor, SetForegroundColor,
};
use crossterm::terminal::Clear;
use ratatui::layout::Position;
use ratatui::style::{Color, Modifier};
use unicode_width::UnicodeWidthStr;

use super::diff::DrawCommand;

pub(super) fn draw_commands<I>(writer: &mut impl Write, commands: I) -> io::Result<()>
where
    I: Iterator<Item = DrawCommand>,
{
    let mut fg = Color::Reset;
    let mut bg = Color::Reset;
    let mut modifier = Modifier::empty();
    let mut expected_cursor: Option<Position> = None;

    for command in commands {
        let (x, y) = match &command {
            DrawCommand::Put { x, y, .. } => (*x, *y),
            DrawCommand::ClearToEnd { x, y, .. } => (*x, *y),
        };

        if !matches!(expected_cursor, Some(pos) if x == pos.x && y == pos.y) {
            queue!(writer, MoveTo(x, y))?;
        }

        match command {
            DrawCommand::Put { cell, .. } => {
                if cell.modifier != modifier {
                    ModifierDiff {
                        from: modifier,
                        to: cell.modifier,
                    }
                    .queue(writer)?;
                    modifier = cell.modifier;
                }
                if cell.fg != fg || cell.bg != bg {
                    queue!(
                        writer,
                        SetForegroundColor(to_crossterm_color(cell.fg)),
                        SetBackgroundColor(to_crossterm_color(cell.bg))
                    )?;
                    fg = cell.fg;
                    bg = cell.bg;
                }
                queue!(writer, Print(cell.symbol()))?;
                expected_cursor = Some(Position {
                    x: x.saturating_add(display_width(cell.symbol()).max(1) as u16),
                    y,
                });
            }
            DrawCommand::ClearToEnd { bg: clear_bg, .. } => {
                queue!(writer, SetAttribute(CAttribute::Reset))?;
                modifier = Modifier::empty();
                fg = Color::Reset;
                queue!(writer, SetBackgroundColor(to_crossterm_color(clear_bg)))?;
                bg = clear_bg;
                queue!(writer, Clear(crossterm::terminal::ClearType::UntilNewLine))?;
                expected_cursor = None;
            }
        }
    }

    queue!(
        writer,
        SetForegroundColor(crossterm::style::Color::Reset),
        SetBackgroundColor(crossterm::style::Color::Reset),
        SetAttribute(CAttribute::Reset)
    )?;
    Ok(())
}

fn display_width(text: &str) -> usize {
    UnicodeWidthStr::width(text)
}

fn to_crossterm_color(color: Color) -> crossterm::style::Color {
    match color {
        Color::Reset => crossterm::style::Color::Reset,
        Color::Black => crossterm::style::Color::Black,
        Color::Red => crossterm::style::Color::DarkRed,
        Color::Green => crossterm::style::Color::DarkGreen,
        Color::Yellow => crossterm::style::Color::DarkYellow,
        Color::Blue => crossterm::style::Color::DarkBlue,
        Color::Magenta => crossterm::style::Color::DarkMagenta,
        Color::Cyan => crossterm::style::Color::DarkCyan,
        Color::Gray => crossterm::style::Color::Grey,
        Color::DarkGray => crossterm::style::Color::DarkGrey,
        Color::LightRed => crossterm::style::Color::Red,
        Color::LightGreen => crossterm::style::Color::Green,
        Color::LightYellow => crossterm::style::Color::Yellow,
        Color::LightBlue => crossterm::style::Color::Blue,
        Color::LightMagenta => crossterm::style::Color::Magenta,
        Color::LightCyan => crossterm::style::Color::Cyan,
        Color::White => crossterm::style::Color::White,
        Color::Rgb(r, g, b) => crossterm::style::Color::Rgb { r, g, b },
        Color::Indexed(index) => crossterm::style::Color::AnsiValue(index),
    }
}

struct ModifierDiff {
    from: Modifier,
    to: Modifier,
}

#[cfg(test)]
mod tests {
    use ratatui::buffer::Cell;
    use ratatui::style::Color;

    use super::super::diff::DrawCommand;
    use super::draw_commands;

    #[test]
    fn draw_commands_repositions_after_wide_cells() {
        let mut first = Cell::default();
        first.set_symbol("你");
        let mut second = Cell::default();
        second.set_symbol("A");

        let mut out = Vec::new();
        draw_commands(
            &mut out,
            vec![
                DrawCommand::Put {
                    x: 0,
                    y: 0,
                    cell: first,
                },
                DrawCommand::Put {
                    x: 1,
                    y: 0,
                    cell: second,
                },
            ]
            .into_iter(),
        )
        .expect("draw should succeed");

        let rendered = String::from_utf8_lossy(&out);
        assert!(
            rendered.contains("\x1b[1;2HA"),
            "adjacent update after a wide cell must reposition explicitly: {rendered:?}"
        );
    }

    #[test]
    fn draw_commands_repositions_after_clear_to_end() {
        let mut cell = Cell::default();
        cell.set_symbol("A");

        let mut out = Vec::new();
        draw_commands(
            &mut out,
            vec![
                DrawCommand::ClearToEnd {
                    x: 0,
                    y: 0,
                    bg: Color::Reset,
                },
                DrawCommand::Put { x: 1, y: 0, cell },
            ]
            .into_iter(),
        )
        .expect("draw should succeed");

        let rendered = String::from_utf8_lossy(&out);
        assert!(
            rendered.contains("\x1b[1;2HA"),
            "update after clear should not rely on stale cursor position: {rendered:?}"
        );
    }

    #[test]
    fn draw_commands_reapplies_foreground_after_clear_reset() {
        let mut before_clear = Cell::default();
        before_clear.set_symbol("A");
        before_clear.fg = Color::Rgb(174, 220, 121);
        let mut after_clear = Cell::default();
        after_clear.set_symbol("B");
        after_clear.fg = Color::Rgb(174, 220, 121);

        let mut out = Vec::new();
        draw_commands(
            &mut out,
            vec![
                DrawCommand::Put {
                    x: 0,
                    y: 0,
                    cell: before_clear,
                },
                DrawCommand::ClearToEnd {
                    x: 1,
                    y: 0,
                    bg: Color::Reset,
                },
                DrawCommand::Put {
                    x: 2,
                    y: 0,
                    cell: after_clear,
                },
            ]
            .into_iter(),
        )
        .expect("draw should succeed");

        let rendered = String::from_utf8_lossy(&out);
        let before_second_cell = rendered
            .split("\x1b[1;3H")
            .nth(1)
            .and_then(|tail| tail.split('B').next())
            .unwrap_or_default();
        assert!(
            before_second_cell.contains("\x1b["),
            "clear reset should force foreground color to be emitted again: {rendered:?}"
        );
    }
}

impl ModifierDiff {
    fn queue<W: Write>(self, writer: &mut W) -> io::Result<()> {
        let removed = self.from - self.to;
        if removed.contains(Modifier::REVERSED) {
            queue!(writer, SetAttribute(CAttribute::NoReverse))?;
        }
        if removed.contains(Modifier::BOLD) {
            queue!(writer, SetAttribute(CAttribute::NormalIntensity))?;
            if self.to.contains(Modifier::DIM) {
                queue!(writer, SetAttribute(CAttribute::Dim))?;
            }
        }
        if removed.contains(Modifier::ITALIC) {
            queue!(writer, SetAttribute(CAttribute::NoItalic))?;
        }
        if removed.contains(Modifier::UNDERLINED) {
            queue!(writer, SetAttribute(CAttribute::NoUnderline))?;
        }
        if removed.contains(Modifier::DIM) {
            queue!(writer, SetAttribute(CAttribute::NormalIntensity))?;
        }
        if removed.contains(Modifier::CROSSED_OUT) {
            queue!(writer, SetAttribute(CAttribute::NotCrossedOut))?;
        }

        let added = self.to - self.from;
        if added.contains(Modifier::REVERSED) {
            queue!(writer, SetAttribute(CAttribute::Reverse))?;
        }
        if added.contains(Modifier::BOLD) {
            queue!(writer, SetAttribute(CAttribute::Bold))?;
        }
        if added.contains(Modifier::ITALIC) {
            queue!(writer, SetAttribute(CAttribute::Italic))?;
        }
        if added.contains(Modifier::UNDERLINED) {
            queue!(writer, SetAttribute(CAttribute::Underlined))?;
        }
        if added.contains(Modifier::DIM) {
            queue!(writer, SetAttribute(CAttribute::Dim))?;
        }
        if added.contains(Modifier::CROSSED_OUT) {
            queue!(writer, SetAttribute(CAttribute::CrossedOut))?;
        }

        Ok(())
    }
}
