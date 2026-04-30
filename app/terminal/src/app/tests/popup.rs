use crate::bottom_pane::command_popup;

use super::super::App;

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
fn submit_selected_popup_executes_selected_command() {
    let mut app = App::new();
    app.input = "/he".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_selected_popup();
    assert!(matches!(action, Some(super::super::SubmitAction::Handled)));
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
fn agent_popup_matches_catalog_entries() {
    let mut app = App::new();
    app.set_agent_catalog(vec![
        (
            "agent-123".to_string(),
            "Research Agent".to_string(),
            "fibre".to_string(),
            true,
            "2026-04-28T10:00:00".to_string(),
        ),
        (
            "agent-456".to_string(),
            "Ops Agent".to_string(),
            "simple".to_string(),
            false,
            "2026-04-27T09:00:00".to_string(),
        ),
    ]);
    app.input = "/agent set agent".to_string();
    app.input_cursor = app.input.len();

    let matches = app.popup_matches();
    assert_eq!(matches[0].command, "agent-123");
    assert!(matches[0].description.contains("fibre"));
    assert!(matches[0].description.contains("default"));
    assert!(matches[0]
        .preview_lines
        .iter()
        .any(|line| line.contains("updated: 2026-04-28T10:00:00")));
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
        Some(super::super::SubmitAction::SetDefaultProvider(provider_id))
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
        Some(super::super::SubmitAction::EnableSkill(skill)) if skill == "github"
    ));
}

#[test]
fn submit_selected_agent_popup_executes_agent_command() {
    let mut app = App::new();
    app.set_agent_catalog(vec![(
        "agent-123".to_string(),
        "Research Agent".to_string(),
        "multi".to_string(),
        false,
        "2026-04-28T10:00:00".to_string(),
    )]);
    app.input = "/agent set ag".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_selected_popup();
    assert!(matches!(action, Some(super::super::SubmitAction::Handled)));
    assert_eq!(app.selected_agent_id.as_deref(), Some("agent-123"));
}
