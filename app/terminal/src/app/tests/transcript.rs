use crate::app_render::render_assistant_body;

use super::super::{App, MessageKind};

#[test]
fn transcript_messages_render_with_role_headers() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    app.push_message(MessageKind::Assistant, "world");

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("• "));
    assert!(rendered.contains("You"));
    assert!(rendered.contains("Sage"));
    assert!(rendered.contains("hello"));
    assert!(rendered.contains("world"));
}

#[test]
fn assistant_tables_render_as_grid_lines() {
    let lines = render_assistant_body(
        "| name | value |\n| ---- | ----- |\n| mode | simple |\n| loops | 50 |",
    );
    let rendered = lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("│ name"));
    assert!(rendered.contains("├"));
    assert!(rendered.contains("simple"));
}

#[test]
fn assistant_long_code_blocks_are_folded() {
    let code =
        "```rust\nline1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n```";
    let lines = render_assistant_body(code);
    let rendered = lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("code rust"));
    assert!(rendered.contains("… 2 more lines"));
}

#[test]
fn streamed_multiline_assistant_output_keeps_single_role_header() {
    let mut app = App::new();
    app.append_assistant_chunk("line one\n");
    app.append_assistant_chunk("line two\n");
    app.complete_request();

    let rendered = app
        .pending_history_lines
        .iter()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert_eq!(rendered.matches("Sage").count(), 1);
    assert!(rendered.contains("line one"));
    assert!(rendered.contains("line two"));
}

#[test]
fn transcript_overlay_opens_after_history_is_committed() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    let _ = app.take_pending_history_lines();
    app.open_transcript_overlay();

    let props = app.transcript_overlay_props(90).expect("transcript props");
    assert!(props.lines.iter().any(|line| {
        line.spans
            .iter()
            .any(|span| span.content.as_ref().contains("hello"))
    }));
}

#[test]
fn transcript_overlay_scrolls_for_long_history() {
    let mut app = App::new();
    for idx in 0..40 {
        app.push_message(MessageKind::Assistant, format!("line {idx}"));
    }
    let _ = app.take_pending_history_lines();
    app.open_transcript_overlay();
    assert!(app.scroll_transcript_overlay_down(5));
    let props = app.transcript_overlay_props(90).expect("transcript props");
    assert!(props.scroll > 0);
}
