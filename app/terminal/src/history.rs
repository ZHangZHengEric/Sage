use std::fmt;
use std::io;
use std::io::Write;

use crossterm::cursor::MoveTo;
use crossterm::queue;
use crossterm::style::{
    Attribute as CAttribute, Print, SetAttribute, SetBackgroundColor, SetForegroundColor,
};
use crossterm::terminal::{Clear, ClearType};
use ratatui::style::{Color as RatatuiColor, Modifier};
use ratatui::text::{Line, Span};

use crate::custom_terminal::{BackendImpl, Terminal};

pub fn insert_history_lines(
    terminal: &mut Terminal<BackendImpl>,
    lines: &[Line<'static>],
) -> io::Result<()> {
    if lines.is_empty() {
        return Ok(());
    }

    let screen_size = terminal.size()?;
    let mut area = terminal.viewport_area();
    let last_cursor_pos = terminal.last_known_cursor_pos();
    let wrapped_lines = lines.len().min(u16::MAX as usize) as u16;
    let writer = terminal.backend_mut();

    let cursor_top = if area.bottom() < screen_size.height {
        let scroll_amount = wrapped_lines.min(screen_size.height.saturating_sub(area.bottom()));
        if scroll_amount > 0 {
            let top_1based = area.top() + 1;
            queue!(writer, SetScrollRegion(top_1based..screen_size.height))?;
            queue!(writer, MoveTo(0, area.top()))?;
            for _ in 0..scroll_amount {
                queue!(writer, Print("\x1bM"))?;
            }
            queue!(writer, ResetScrollRegion)?;
            let cursor_top = area.top().saturating_sub(1);
            area.y += scroll_amount;
            cursor_top
        } else {
            area.top().saturating_sub(1)
        }
    } else {
        area.top().saturating_sub(1)
    };

    if area.top() > 0 {
        queue!(writer, SetScrollRegion(1..area.top()))?;
    }
    queue!(writer, MoveTo(0, cursor_top))?;

    for line in lines {
        queue!(writer, Print("\r\n"))?;
        write_history_line(writer, line)?;
    }

    if area.top() > 0 {
        queue!(writer, ResetScrollRegion)?;
    }
    queue!(writer, MoveTo(last_cursor_pos.x, last_cursor_pos.y))?;
    let _ = writer;

    if area != terminal.viewport_area() {
        terminal.set_viewport_area(area);
    }

    Ok(())
}

fn write_history_line<W: Write>(writer: &mut W, line: &Line<'static>) -> io::Result<()> {
    queue!(
        writer,
        SetForegroundColor(
            line.style
                .fg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset)
        ),
        SetBackgroundColor(
            line.style
                .bg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset)
        ),
        Clear(ClearType::UntilNewLine)
    )?;

    let merged_spans = line.spans.iter().map(|span| Span {
        style: span.style.patch(line.style),
        content: span.content.clone(),
    });
    write_spans(writer, merged_spans)?;
    queue!(
        writer,
        SetForegroundColor(crossterm::style::Color::Reset),
        SetBackgroundColor(crossterm::style::Color::Reset),
        SetAttribute(CAttribute::Reset)
    )?;
    Ok(())
}

fn write_spans<'a, W, I>(writer: &mut W, spans: I) -> io::Result<()>
where
    W: Write,
    I: IntoIterator<Item = Span<'a>>,
{
    let mut fg = crossterm::style::Color::Reset;
    let mut bg = crossterm::style::Color::Reset;
    let mut modifier = Modifier::empty();

    for span in spans {
        if span
            .style
            .fg
            .map(to_crossterm_color)
            .unwrap_or(crossterm::style::Color::Reset)
            != fg
            || span
                .style
                .bg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset)
                != bg
        {
            fg = span
                .style
                .fg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset);
            bg = span
                .style
                .bg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset);
            queue!(writer, SetForegroundColor(fg), SetBackgroundColor(bg))?;
        }

        if span.style.add_modifier != modifier {
            queue!(writer, SetAttribute(CAttribute::Reset))?;
            modifier = span.style.add_modifier;
            fg = crossterm::style::Color::Reset;
            bg = crossterm::style::Color::Reset;
            let next_fg = span
                .style
                .fg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset);
            let next_bg = span
                .style
                .bg
                .map(to_crossterm_color)
                .unwrap_or(crossterm::style::Color::Reset);
            if next_fg != fg || next_bg != bg {
                fg = next_fg;
                bg = next_bg;
                queue!(writer, SetForegroundColor(fg), SetBackgroundColor(bg))?;
            }
            if modifier.contains(Modifier::BOLD) {
                queue!(writer, SetAttribute(CAttribute::Bold))?;
            }
            if modifier.contains(Modifier::ITALIC) {
                queue!(writer, SetAttribute(CAttribute::Italic))?;
            }
            if modifier.contains(Modifier::UNDERLINED) {
                queue!(writer, SetAttribute(CAttribute::Underlined))?;
            }
            if modifier.contains(Modifier::DIM) {
                queue!(writer, SetAttribute(CAttribute::Dim))?;
            }
        }

        queue!(writer, Print(span.content.as_ref()))?;
    }

    Ok(())
}

fn to_crossterm_color(color: RatatuiColor) -> crossterm::style::Color {
    match color {
        RatatuiColor::Reset => crossterm::style::Color::Reset,
        RatatuiColor::Black => crossterm::style::Color::Black,
        RatatuiColor::Red => crossterm::style::Color::DarkRed,
        RatatuiColor::Green => crossterm::style::Color::DarkGreen,
        RatatuiColor::Yellow => crossterm::style::Color::DarkYellow,
        RatatuiColor::Blue => crossterm::style::Color::DarkBlue,
        RatatuiColor::Magenta => crossterm::style::Color::DarkMagenta,
        RatatuiColor::Cyan => crossterm::style::Color::DarkCyan,
        RatatuiColor::Gray => crossterm::style::Color::Grey,
        RatatuiColor::DarkGray => crossterm::style::Color::DarkGrey,
        RatatuiColor::LightRed => crossterm::style::Color::Red,
        RatatuiColor::LightGreen => crossterm::style::Color::Green,
        RatatuiColor::LightYellow => crossterm::style::Color::Yellow,
        RatatuiColor::LightBlue => crossterm::style::Color::Blue,
        RatatuiColor::LightMagenta => crossterm::style::Color::Magenta,
        RatatuiColor::LightCyan => crossterm::style::Color::Cyan,
        RatatuiColor::White => crossterm::style::Color::White,
        RatatuiColor::Rgb(r, g, b) => crossterm::style::Color::Rgb { r, g, b },
        RatatuiColor::Indexed(index) => crossterm::style::Color::AnsiValue(index),
    }
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
    use ratatui::style::{Color, Modifier, Style};
    use ratatui::text::{Line, Span};

    use super::write_history_line;

    #[test]
    fn history_line_reapplies_color_after_modifier_reset() {
        crossterm::style::Colored::set_ansi_color_disabled(false);
        let line = Line::from(vec![
            Span::styled("plain", Style::default().fg(Color::Rgb(143, 190, 246))),
            Span::styled(
                "bold",
                Style::default()
                    .fg(Color::Rgb(143, 190, 246))
                    .add_modifier(Modifier::BOLD),
            ),
        ]);
        let mut output = Vec::new();

        write_history_line(&mut output, &line).expect("history line should render");

        let rendered = String::from_utf8_lossy(&output);
        let bold_start = rendered.find("bold").expect("bold text should render");
        let before_bold = &rendered[..bold_start];
        let reset_start = before_bold.rfind("\x1b[0m").expect("modifier reset");
        let after_reset = &before_bold[reset_start..];
        assert!(
            after_reset.contains("\x1b[38;2;143;190;246m"),
            "foreground color should be re-applied after reset: {rendered:?}"
        );
    }
}
