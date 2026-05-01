use anyhow::Result;

use crate::app::{App, MessageKind};
use crate::backend::list_skills as fetch_skills;
use crate::terminal_support::format_skills_list;

pub(super) fn list_skills(app: &mut App) -> Result<bool> {
    match fetch_skills(
        &app.user_id,
        app.selected_agent_id.as_deref(),
        app.workspace_override_path(),
    ) {
        Ok(skills) => {
            app.set_skill_catalog(
                skills
                    .iter()
                    .map(|skill| {
                        (
                            skill.name.clone(),
                            skill.description.clone(),
                            skill.source.clone(),
                        )
                    })
                    .collect(),
            );
            app.push_message(
                MessageKind::Tool,
                format_skills_list(&skills, &app.selected_skills),
            );
            app.set_status(format!("skills  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(MessageKind::System, format!("failed to list skills: {err}"));
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn enable_skill(app: &mut App, skill: String) -> Result<bool> {
    match fetch_skills(
        &app.user_id,
        app.selected_agent_id.as_deref(),
        app.workspace_override_path(),
    ) {
        Ok(skills) => {
            app.set_skill_catalog(
                skills
                    .iter()
                    .map(|skill| {
                        (
                            skill.name.clone(),
                            skill.description.clone(),
                            skill.source.clone(),
                        )
                    })
                    .collect(),
            );
            if skills.iter().any(|item| item.name == skill) {
                app.enable_skill(skill);
            } else {
                app.push_message(
                    MessageKind::System,
                    format!("unknown skill: {skill}\nRun /skills to inspect visible skills."),
                );
                app.set_status(format!("skills  {}", app.session_id));
            }
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to validate skill: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn disable_skill(app: &mut App, skill: &str) -> Result<bool> {
    app.disable_skill(skill);
    Ok(true)
}

pub(super) fn clear_skills(app: &mut App) -> Result<bool> {
    app.clear_skills();
    Ok(true)
}
