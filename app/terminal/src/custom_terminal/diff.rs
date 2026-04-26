use ratatui::buffer::{Buffer, Cell};
use ratatui::layout::{Rect, Size};
use ratatui::style::{Color, Modifier};
use unicode_width::UnicodeWidthStr;

pub(super) fn viewport_rect(screen_size: Size, viewport_height: u16, anchor_y: u16) -> Rect {
    let height = viewport_height.max(1).min(screen_size.height.max(1));
    let max_y = screen_size.height.saturating_sub(height);
    let y = anchor_y.min(max_y);
    Rect::new(0, y, screen_size.width, height)
}

#[derive(Debug)]
pub(super) enum DrawCommand {
    Put { x: u16, y: u16, cell: Cell },
    ClearToEnd { x: u16, y: u16, bg: Color },
}

pub(super) fn diff_buffers(previous: &Buffer, next: &Buffer) -> Vec<DrawCommand> {
    let mut updates = Vec::new();
    let mut last_nonblank_columns = vec![0; previous.area.height as usize];

    for y in 0..previous.area.height {
        let row_start = y as usize * previous.area.width as usize;
        let row_end = row_start + previous.area.width as usize;
        let row = &next.content[row_start..row_end];
        let bg = row.last().map(|cell| cell.bg).unwrap_or(Color::Reset);

        let mut last_nonblank_column = 0usize;
        let mut column = 0usize;
        while column < row.len() {
            let cell = &row[column];
            let width = display_width(cell.symbol()).max(1);
            if cell.symbol() != " " || cell.bg != bg || cell.modifier != Modifier::empty() {
                last_nonblank_column = column + (width.saturating_sub(1));
            }
            column += width;
        }

        if last_nonblank_column + 1 < row.len() {
            let (x, y) = previous.pos_of(row_start + last_nonblank_column + 1);
            updates.push(DrawCommand::ClearToEnd { x, y, bg });
        }

        last_nonblank_columns[y as usize] = last_nonblank_column as u16;
    }

    let mut invalidated = 0usize;
    let mut to_skip = 0usize;
    for (i, (current, prior)) in next.content.iter().zip(previous.content.iter()).enumerate() {
        if !current.skip && (current != prior || invalidated > 0) && to_skip == 0 {
            let (x, y) = previous.pos_of(i);
            let row = i / previous.area.width as usize;
            if x <= last_nonblank_columns[row] {
                updates.push(DrawCommand::Put {
                    x,
                    y,
                    cell: current.clone(),
                });
            }
        }

        to_skip = display_width(current.symbol()).saturating_sub(1);
        let affected_width = std::cmp::max(
            display_width(current.symbol()),
            display_width(prior.symbol()),
        );
        invalidated = std::cmp::max(affected_width, invalidated).saturating_sub(1);
    }

    updates
}

fn display_width(text: &str) -> usize {
    if !text.contains('\x1B') {
        return UnicodeWidthStr::width(text);
    }

    let mut visible = String::with_capacity(text.len());
    let mut chars = text.chars();
    while let Some(ch) = chars.next() {
        if ch == '\x1B' && chars.clone().next() == Some(']') {
            let _ = chars.next();
            for c in chars.by_ref() {
                if c == '\x07' {
                    break;
                }
            }
            continue;
        }
        visible.push(ch);
    }
    UnicodeWidthStr::width(visible.as_str())
}
