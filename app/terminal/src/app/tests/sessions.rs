use super::super::{App, MessageKind, SessionPickerEntry, SessionPickerMode};

#[test]
fn session_picker_props_include_selected_preview_panel() {
    let mut app = App::new();
    app.open_session_picker(
        SessionPickerMode::Browse,
        vec![SessionPickerEntry {
            session_id: "local-000123".to_string(),
            title: "Refactor footer".to_string(),
            message_count: 12,
            updated_at: "2026-04-24 13:20".to_string(),
            preview: Some("Last message preview".to_string()),
        }],
    );

    let props = app.session_picker_props().expect("picker props");
    assert_eq!(props.preview_title.as_deref(), Some("Selected Session"));
    assert!(props
        .preview_lines
        .iter()
        .any(|line| line.contains("local-000123")));
    assert!(props
        .preview_lines
        .iter()
        .any(|line| line.contains("Last message preview")));
}

#[test]
fn session_picker_preview_truncates_long_multiline_preview() {
    let mut app = App::new();
    app.open_session_picker(
        SessionPickerMode::Browse,
        vec![SessionPickerEntry {
            session_id: "local-000123".to_string(),
            title: "A very long title that should be shortened inside the preview panel for readability".to_string(),
            message_count: 12,
            updated_at: "2026-04-24 13:20".to_string(),
            preview: Some("line one\nline two\nline three\nline four".to_string()),
        }],
    );

    let props = app.session_picker_props().expect("picker props");
    assert!(props
        .preview_lines
        .iter()
        .any(|line| line.starts_with("title  A very long title")));
    assert!(props.preview_lines.iter().any(|line| line == "…"));
}

#[test]
fn session_picker_selection_returns_resume_action() {
    let mut app = App::new();
    app.open_session_picker(
        SessionPickerMode::Resume,
        vec![
            SessionPickerEntry {
                session_id: "local-000123".to_string(),
                title: "Provider work".to_string(),
                message_count: 12,
                updated_at: "2026-04-24T12:00:00Z".to_string(),
                preview: Some("last preview".to_string()),
            },
            SessionPickerEntry {
                session_id: "local-000122".to_string(),
                title: "Footer work".to_string(),
                message_count: 4,
                updated_at: "2026-04-23T10:00:00Z".to_string(),
                preview: None,
            },
        ],
    );
    assert!(app.select_next_session_picker_item());

    let action = app.submit_session_picker_selection();
    assert!(matches!(
        action,
        Some(super::super::SubmitAction::ResumeSession(session_id))
            if session_id == "local-000122"
    ));
}

#[test]
fn session_picker_filter_narrows_items() {
    let mut app = App::new();
    app.open_session_picker(
        SessionPickerMode::Browse,
        vec![
            SessionPickerEntry {
                session_id: "local-000123".to_string(),
                title: "Provider work".to_string(),
                message_count: 12,
                updated_at: "2026-04-24T12:00:00Z".to_string(),
                preview: Some("default provider".to_string()),
            },
            SessionPickerEntry {
                session_id: "local-000122".to_string(),
                title: "Footer work".to_string(),
                message_count: 4,
                updated_at: "2026-04-23T10:00:00Z".to_string(),
                preview: None,
            },
        ],
    );
    assert!(app.session_picker_insert_char('p'));

    let props = app
        .session_picker_props()
        .expect("session picker should render");
    assert_eq!(props.items.len(), 1);
    assert_eq!(props.items[0].primary, "local-000123");
}

#[test]
fn load_resumed_session_replays_messages_without_summary_banner() {
    let mut app = App::new();
    app.load_resumed_session(
        "local-000123".to_string(),
        vec![
            (MessageKind::User, "hello".to_string()),
            (MessageKind::Assistant, "world".to_string()),
        ],
    );

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("hello"));
    assert!(rendered.contains("world"));
    assert!(!rendered.contains("resumed local-000123"));
}
