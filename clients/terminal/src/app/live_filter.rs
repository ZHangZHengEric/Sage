use std::collections::BTreeSet;

pub(super) fn clean_assistant_live_text(text: &mut String) {
    strip_loop_diagnostics(text);
    dedupe_repeated_assistant_lines(text);
    collapse_adjacent_repeated_phrases(text);
}

pub(super) fn filter_completed_duplicate_assistant_lines(
    text: &mut String,
    seen: &mut BTreeSet<String>,
    in_code_block: &mut bool,
) {
    let Some(split_at) = text.rfind('\n') else {
        return;
    };

    let completed = text[..split_at].to_string();
    let remainder = text[split_at + 1..].to_string();
    let mut kept = Vec::new();
    let mut changed = false;

    for line in completed.lines() {
        let normalized = line.trim();
        if normalized.starts_with("```") {
            *in_code_block = !*in_code_block;
            kept.push(line);
            continue;
        }
        if !*in_code_block && !normalized.is_empty() && !seen.insert(normalized.to_string()) {
            changed = true;
            continue;
        }
        kept.push(line);
    }

    if !changed {
        return;
    }

    let mut filtered = kept.join("\n");
    if !filtered.is_empty() {
        filtered.push('\n');
    }
    filtered.push_str(&remainder);
    *text = filtered;
}

pub(super) fn filter_final_duplicate_assistant_text(
    text: &mut String,
    seen: &mut BTreeSet<String>,
    in_code_block: &mut bool,
) {
    if text.contains('\n') {
        filter_completed_duplicate_assistant_lines(text, seen, in_code_block);
    }

    let normalized = text.trim();
    if normalized.is_empty()
        || normalized.starts_with("```")
        || *in_code_block
        || seen.insert(normalized.to_string())
    {
        return;
    }

    text.clear();
}

fn strip_loop_diagnostics(text: &mut String) {
    strip_from_marker(
        text,
        "Self-check: Repeating execution loop detected",
        "clarification question.",
    );
    strip_from_marker(text, "检测到任务进入重复循环", "继续。");
}

fn strip_from_marker(text: &mut String, start_marker: &str, end_marker: &str) {
    while let Some(start) = text.find(start_marker) {
        let tail = &text[start..];
        let end = tail
            .find(end_marker)
            .map(|index| start + index + end_marker.len())
            .unwrap_or_else(|| text.len());
        text.replace_range(start..end, "");
    }
}

fn dedupe_repeated_assistant_lines(text: &mut String) {
    if !text.contains('\n') {
        return;
    }

    let had_trailing_newline = text.ends_with('\n');
    let mut deduped = Vec::new();
    let mut seen_non_empty = BTreeSet::new();
    let mut changed = false;
    let mut in_code_block = false;

    for line in text.lines() {
        let normalized = line.trim();
        if normalized.starts_with("```") {
            in_code_block = !in_code_block;
            deduped.push(line);
            continue;
        }
        if !in_code_block
            && !normalized.is_empty()
            && !seen_non_empty.insert(normalized.to_string())
        {
            changed = true;
            continue;
        }
        deduped.push(line);
    }

    if !changed {
        return;
    }

    *text = deduped.join("\n");
    if had_trailing_newline {
        text.push('\n');
    }
}

fn collapse_adjacent_repeated_phrases(text: &mut String) {
    if text.contains("```") || text.chars().count() > 4_000 {
        return;
    }

    let had_trailing_newline = text.ends_with('\n');
    let mut collapsed = text
        .lines()
        .map(collapse_line_repeats)
        .collect::<Vec<_>>()
        .join("\n");
    if had_trailing_newline {
        collapsed.push('\n');
    }
    if collapsed != *text {
        *text = collapsed;
    }
}

fn collapse_line_repeats(line: &str) -> String {
    let chars = line.chars().collect::<Vec<_>>();
    if chars.len() < 16 {
        return line.to_string();
    }

    let mut output = Vec::with_capacity(chars.len());
    let mut index = 0;
    while index < chars.len() {
        let remaining = chars.len() - index;
        let max_len = (remaining / 2).min(160);
        let mut collapsed = false;
        for len in (8..=max_len).rev() {
            let left = &chars[index..index + len];
            let right = &chars[index + len..index + (len * 2)];
            if left == right && repeated_phrase_is_user_text(left) {
                output.extend_from_slice(left);
                index += len * 2;
                collapsed = true;
                break;
            }
        }
        if !collapsed {
            output.push(chars[index]);
            index += 1;
        }
    }

    output.into_iter().collect()
}

fn repeated_phrase_is_user_text(chars: &[char]) -> bool {
    let text = chars.iter().collect::<String>();
    text.contains('。')
        || text.contains('！')
        || text.contains('？')
        || text.contains("Hello")
        || text.contains("hello")
}
