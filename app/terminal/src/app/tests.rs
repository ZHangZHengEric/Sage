use crate::app_render::render_assistant_body;
use crate::bottom_pane::command_popup;

use super::{ActiveSurfaceKind, App, MessageKind, SessionPickerEntry, SessionPickerMode};

#[test]
fn slash_popup_matches_prefix_commands() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();

    let matches = app.popup_matches();
    assert_eq!(matches[0].command, "/providers");
    assert_eq!(matches[1].command, "/provider");
}

#[test]
fn slash_popup_exposes_usage_and_example_preview() {
    let mut app = App::new();
    app.input = "/he".to_string();
    app.input_cursor = app.input.len();

    let props = app.popup_props().expect("popup props");
    let selected = props
        .items
        .iter()
        .find(|item| item.selected)
        .expect("selected");
    assert!(selected
        .preview_lines
        .iter()
        .any(|line| line.contains("usage: /help [command]")));
    assert!(selected
        .preview_lines
        .iter()
        .any(|line| line.contains("example: /help provider")));
}

#[test]
fn slash_popup_selection_wraps() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();

    assert_eq!(app.slash_popup_selected, 0);
    assert!(app.select_next_popup_item());
    assert_eq!(app.slash_popup_selected, 1);
    assert!(app.select_next_popup_item());
    assert_eq!(app.slash_popup_selected, 0);
    assert!(app.select_previous_popup_item());
    assert_eq!(app.slash_popup_selected, 1);
}

#[test]
fn slash_popup_selection_can_reach_commands_beyond_first_visible_page() {
    let mut app = App::new();
    app.input = "/".to_string();
    app.input_cursor = app.input.len();

    for _ in 0..4 {
        assert!(app.select_next_popup_item());
    }

    let props = command_popup::props_from_matches(&app.popup_matches(), app.slash_popup_selected)
        .expect("popup props");
    assert_eq!(app.slash_popup_selected, 4);
    assert_eq!(
        props.items.last().map(|item| item.command.as_str()),
        Some("/resume")
    );
    assert!(props.items.last().is_some_and(|item| item.selected));
}

#[test]
fn autocomplete_popup_replaces_input_with_selected_command() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();
    assert!(app.select_next_popup_item());

    assert!(app.autocomplete_popup());
    assert_eq!(app.input, "/provider ".to_string());
    assert_eq!(app.input_cursor, app.input.len());
    assert_eq!(app.active_surface_kind(), None);
}

#[test]
fn welcome_banner_renders_in_idle_region_before_transcript() {
    let app = App::new();
    let lines = app.rendered_idle_lines(120);

    assert!(!lines.is_empty());
    let rendered = lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("Tip: "));
}

#[test]
fn typing_input_keeps_welcome_banner_visible() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let lines = app.rendered_idle_lines(120);

    assert!(!lines.is_empty());
}

#[test]
fn submitting_message_hides_welcome_banner() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    assert!(app.rendered_idle_lines(120).is_empty());
}

#[test]
fn first_transcript_materializes_welcome_into_history() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("Tip: "));
    assert!(rendered.contains("hello"));
    assert!(app.rendered_idle_lines(120).is_empty());
}

#[test]
fn help_command_opens_overlay_without_queueing_history() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, super::SubmitAction::Handled));
    assert!(app.help_overlay_props().is_some());
    assert!(app.pending_history_lines.is_empty());
}

#[test]
fn help_command_topic_opens_detail_overlay() {
    let mut app = App::new();
    app.input = "/help provider".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, super::SubmitAction::Handled));
    let props = app.help_overlay_props().expect("help overlay should open");
    assert_eq!(props.title, "Help  /provider");
    assert!(props
        .sections
        .iter()
        .flat_map(|section| section.items.iter())
        .any(|item| item.value.contains("/provider create")));
}

#[test]
fn submit_selected_popup_executes_selected_command() {
    let mut app = App::new();
    app.input = "/he".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_selected_popup();
    assert!(matches!(action, Some(super::SubmitAction::Handled)));
    assert!(app.help_overlay_props().is_some());
}

#[test]
fn provider_popup_matches_catalog_entries() {
    let mut app = App::new();
    app.set_provider_catalog(vec![
        (
            "provider-123".to_string(),
            "deepseek".to_string(),
            "deepseek-chat".to_string(),
            "https://api.deepseek.com/v1".to_string(),
            true,
        ),
        (
            "provider-456".to_string(),
            "openai".to_string(),
            "gpt-5".to_string(),
            "https://api.openai.com/v1".to_string(),
            false,
        ),
    ]);
    app.input = "/provider inspect pro".to_string();
    app.input_cursor = app.input.len();

    let matches = app.popup_matches();
    assert_eq!(matches[0].command, "provider-123");
    assert!(matches[0].description.contains("default"));
    assert!(matches[0]
        .preview_lines
        .iter()
        .any(|line| line.contains("base: https://api.deepseek.com/v1")));
}

#[test]
fn skill_add_popup_matches_catalog_entries() {
    let mut app = App::new();
    app.set_skill_catalog(vec![
        (
            "github".to_string(),
            "Inspect pull requests and issues".to_string(),
            "plugin".to_string(),
        ),
        (
            "openai-docs".to_string(),
            "Use official OpenAI docs".to_string(),
            "system".to_string(),
        ),
    ]);
    app.input = "/skill add git".to_string();
    app.input_cursor = app.input.len();

    let matches = app.popup_matches();
    assert_eq!(matches[0].command, "github");
    assert!(matches[0].description.contains("plugin"));
    assert!(matches[0]
        .preview_lines
        .iter()
        .any(|line| line.contains("Inspect pull requests")));
}

#[test]
fn skill_remove_popup_uses_selected_skills() {
    let mut app = App::new();
    app.selected_skills = vec!["github".to_string(), "openai-docs".to_string()];
    app.set_skill_catalog(vec![
        (
            "github".to_string(),
            "Inspect pull requests and issues".to_string(),
            "plugin".to_string(),
        ),
        (
            "openai-docs".to_string(),
            "Use official OpenAI docs".to_string(),
            "system".to_string(),
        ),
    ]);
    app.input = "/skill remove open".to_string();
    app.input_cursor = app.input.len();

    let matches = app.popup_matches();
    assert_eq!(matches[0].command, "openai-docs");
    assert!(matches[0].description.contains("active"));
    assert!(matches[0]
        .preview_lines
        .iter()
        .any(|line| line.contains("will be removed")));
}

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

#[test]
fn help_surface_takes_priority_over_popup_surface() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();

    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Help));
}

#[test]
fn closing_popup_surface_clears_input_without_quitting() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();

    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Popup));
    assert!(app.close_active_surface());
    assert!(app.input.is_empty());
    assert_eq!(app.active_surface_kind(), None);
    assert!(!app.should_quit);
}

#[test]
fn submit_selected_provider_popup_returns_provider_action() {
    let mut app = App::new();
    app.set_provider_catalog(vec![(
        "provider-123".to_string(),
        "deepseek".to_string(),
        "deepseek-chat".to_string(),
        "https://api.deepseek.com/v1".to_string(),
        false,
    )]);
    app.input = "/provider default ".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_selected_popup();
    assert!(matches!(
        action,
        Some(super::SubmitAction::SetDefaultProvider(provider_id))
            if provider_id == "provider-123"
    ));
}

#[test]
fn submit_selected_skill_popup_returns_skill_action() {
    let mut app = App::new();
    app.set_skill_catalog(vec![(
        "github".to_string(),
        "Inspect pull requests and issues".to_string(),
        "plugin".to_string(),
    )]);
    app.input = "/skill add git".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_selected_popup();
    assert!(matches!(
        action,
        Some(super::SubmitAction::EnableSkill(skill)) if skill == "github"
    ));
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
        Some(super::SubmitAction::ResumeSession(session_id))
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
