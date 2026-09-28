use std::collections::{HashMap, HashSet, VecDeque};

use anyhow::Result;
use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};

#[derive(Clone)]
pub struct PixelSprite {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<Option<Color>>,
}

impl PixelSprite {
    pub fn get(&self, x: usize, y: usize) -> Option<Color> {
        self.pixels[y * self.width + x]
    }
}

pub fn parse_ansi_half_blocks(input: &str) -> Result<PixelSprite> {
    let mut pixel_rows: Vec<Vec<Option<Color>>> = Vec::new();

    for raw_line in input.lines() {
        let mut chars = raw_line.chars().peekable();
        let mut fg = Color::Reset;
        let mut bg = Color::Reset;
        let mut top = Vec::new();
        let mut bottom = Vec::new();

        while let Some(ch) = chars.next() {
            if ch == '\u{1b}' {
                if chars.next() != Some('[') {
                    continue;
                }

                let mut code = String::new();
                while let Some(&next) = chars.peek() {
                    chars.next();
                    if next == 'm' {
                        break;
                    }
                    code.push(next);
                }
                apply_sgr(&code, &mut fg, &mut bg);
                continue;
            }

            if ch == '▀' {
                top.push(color_option(fg));
                bottom.push(color_option(bg));
            }
        }

        pixel_rows.push(top);
        pixel_rows.push(bottom);
    }

    let width = pixel_rows.first().map(|row| row.len()).unwrap_or_default();
    let height = pixel_rows.len();
    let mut sprite = PixelSprite {
        width,
        height,
        pixels: pixel_rows.into_iter().flatten().collect(),
    };
    knock_out_border_background(&mut sprite, 36);
    crop_sprite(&sprite, 1).ok_or_else(|| anyhow::anyhow!("empty mascot sprite after crop"))
}

pub fn render_sprite_to_lines(
    sprite: &PixelSprite,
    area: Rect,
    bg: Color,
) -> (Vec<Line<'static>>, u16) {
    let target = fit_sprite(sprite, area);
    let scaled = scale_sprite(sprite, target.0, target.1);
    let mut lines = Vec::new();
    let mut y = 0usize;
    while y < scaled.height {
        let mut spans = Vec::with_capacity(scaled.width);
        for x in 0..scaled.width {
            let top = scaled.get(x, y);
            let bottom = if y + 1 < scaled.height {
                scaled.get(x, y + 1)
            } else {
                None
            };
            spans.push(match (top, bottom) {
                (None, None) => Span::styled(" ", Style::default().bg(bg)),
                (Some(t), None) => Span::styled("▀", Style::default().fg(t).bg(bg)),
                (None, Some(b)) => Span::styled("▄", Style::default().fg(b).bg(bg)),
                (Some(t), Some(b)) => Span::styled("▀", Style::default().fg(t).bg(b)),
            });
        }
        lines.push(Line::from(spans));
        y += 2;
    }

    (lines, scaled.width as u16)
}

fn apply_sgr(code: &str, fg: &mut Color, bg: &mut Color) {
    if code == "0" {
        *fg = Color::Reset;
        *bg = Color::Reset;
        return;
    }

    let parts = code
        .split(';')
        .filter_map(|part| part.parse::<u16>().ok())
        .collect::<Vec<_>>();
    let mut i = 0;
    while i < parts.len() {
        match parts[i] {
            38 if i + 4 < parts.len() && parts[i + 1] == 2 => {
                *fg = Color::Rgb(parts[i + 2] as u8, parts[i + 3] as u8, parts[i + 4] as u8);
                i += 5;
            }
            48 if i + 4 < parts.len() && parts[i + 1] == 2 => {
                *bg = Color::Rgb(parts[i + 2] as u8, parts[i + 3] as u8, parts[i + 4] as u8);
                i += 5;
            }
            39 => {
                *fg = Color::Reset;
                i += 1;
            }
            49 => {
                *bg = Color::Reset;
                i += 1;
            }
            _ => i += 1,
        }
    }
}

fn color_option(color: Color) -> Option<Color> {
    match color {
        Color::Reset => None,
        _ => Some(color),
    }
}

fn knock_out_border_background(sprite: &mut PixelSprite, tolerance: u8) {
    if sprite.width == 0 || sprite.height == 0 {
        return;
    }

    let border_colors = dominant_border_colors(sprite);
    let mut queue = VecDeque::new();
    let mut seen = HashSet::new();

    for x in 0..sprite.width {
        queue.push_back((x, 0));
        queue.push_back((x, sprite.height - 1));
    }
    for y in 0..sprite.height {
        queue.push_back((0, y));
        queue.push_back((sprite.width - 1, y));
    }

    while let Some((x, y)) = queue.pop_front() {
        if !seen.insert((x, y)) {
            continue;
        }
        let idx = y * sprite.width + x;
        let Some(color) = sprite.pixels[idx] else {
            continue;
        };
        if !matches_any_border_color(color, &border_colors, tolerance) {
            continue;
        }

        sprite.pixels[idx] = None;

        if x > 0 {
            queue.push_back((x - 1, y));
        }
        if x + 1 < sprite.width {
            queue.push_back((x + 1, y));
        }
        if y > 0 {
            queue.push_back((x, y - 1));
        }
        if y + 1 < sprite.height {
            queue.push_back((x, y + 1));
        }
    }
}

fn dominant_border_colors(sprite: &PixelSprite) -> Vec<Color> {
    let mut counts = HashMap::<(u8, u8, u8), usize>::new();
    for x in 0..sprite.width {
        count_color(sprite.get(x, 0), &mut counts);
        count_color(sprite.get(x, sprite.height.saturating_sub(1)), &mut counts);
    }
    for y in 0..sprite.height {
        count_color(sprite.get(0, y), &mut counts);
        count_color(sprite.get(sprite.width.saturating_sub(1), y), &mut counts);
    }
    let mut colors = counts.into_iter().collect::<Vec<_>>();
    colors.sort_by_key(|(_, count)| std::cmp::Reverse(*count));
    colors
        .into_iter()
        .take(4)
        .map(|((r, g, b), _)| Color::Rgb(r, g, b))
        .collect()
}

fn count_color(color: Option<Color>, counts: &mut HashMap<(u8, u8, u8), usize>) {
    if let Some(Color::Rgb(r, g, b)) = color {
        *counts.entry((r, g, b)).or_insert(0) += 1;
    }
}

fn within_tolerance(a: Color, b: Color, tolerance: u8) -> bool {
    match (a, b) {
        (Color::Rgb(ar, ag, ab), Color::Rgb(br, bg, bb)) => {
            ar.abs_diff(br) <= tolerance
                && ag.abs_diff(bg) <= tolerance
                && ab.abs_diff(bb) <= tolerance
        }
        _ => false,
    }
}

fn matches_any_border_color(color: Color, border_colors: &[Color], tolerance: u8) -> bool {
    border_colors
        .iter()
        .copied()
        .any(|candidate| within_tolerance(color, candidate, tolerance))
}

fn crop_sprite(sprite: &PixelSprite, pad: usize) -> Option<PixelSprite> {
    let mut min_x = sprite.width;
    let mut min_y = sprite.height;
    let mut max_x = 0usize;
    let mut max_y = 0usize;
    let mut found = false;

    for y in 0..sprite.height {
        for x in 0..sprite.width {
            if sprite.get(x, y).is_some() {
                found = true;
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }

    if !found {
        return None;
    }

    min_x = min_x.saturating_sub(pad);
    min_y = min_y.saturating_sub(pad);
    max_x = (max_x + pad).min(sprite.width - 1);
    max_y = (max_y + pad).min(sprite.height - 1);

    let width = max_x - min_x + 1;
    let height = max_y - min_y + 1;
    let mut pixels = Vec::with_capacity(width * height);
    for y in min_y..=max_y {
        for x in min_x..=max_x {
            pixels.push(sprite.get(x, y));
        }
    }

    Some(PixelSprite {
        width,
        height,
        pixels,
    })
}

fn fit_sprite(sprite: &PixelSprite, area: Rect) -> (usize, usize) {
    let max_w = area.width.max(1) as f32;
    let max_h = (area.height.max(1) as f32) * 2.0;
    let scale = (max_w / sprite.width as f32)
        .min(max_h / sprite.height as f32)
        .max(1.0);
    let width = ((sprite.width as f32) * scale).round().max(1.0) as usize;
    let mut height = ((sprite.height as f32) * scale).round().max(1.0) as usize;
    if height % 2 != 0 {
        height += 1;
    }
    (
        width.min(area.width as usize),
        height.min((area.height as usize) * 2),
    )
}

fn scale_sprite(sprite: &PixelSprite, width: usize, height: usize) -> PixelSprite {
    let mut pixels = Vec::with_capacity(width * height);
    for y in 0..height {
        let src_y = y * sprite.height / height;
        for x in 0..width {
            let src_x = x * sprite.width / width;
            pixels.push(sprite.get(src_x, src_y));
        }
    }
    PixelSprite {
        width,
        height,
        pixels,
    }
}
