use crate::app::{App, SkillCandidate, SkillPopupMode};
use crate::bottom_pane::command_popup;

impl App {
    pub fn set_skill_catalog(&mut self, skills: Vec<(String, String, String)>) {
        self.skill_catalog = Some(
            skills
                .into_iter()
                .map(|(name, description, source)| SkillCandidate {
                    name,
                    description,
                    source,
                })
                .collect(),
        );
        self.sync_slash_popup_selection();
    }

    pub(super) fn skill_popup_context(&self) -> Option<(SkillPopupMode, &str)> {
        let line = self.input.lines().next().unwrap_or("");
        if let Some(query) = line.strip_prefix("/skill add ") {
            if query.split_whitespace().count() <= 1 {
                return Some((SkillPopupMode::Add, query.trim()));
            }
        }
        if let Some(query) = line.strip_prefix("/skill remove ") {
            if query.split_whitespace().count() <= 1 {
                return Some((SkillPopupMode::Remove, query.trim()));
            }
        }
        None
    }

    pub(super) fn skill_popup_matches(
        &self,
        mode: SkillPopupMode,
        query: &str,
    ) -> Vec<command_popup::CommandMatch> {
        let query = query.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        let mut contains = Vec::new();

        match mode {
            SkillPopupMode::Add => {
                let Some(catalog) = self.skill_catalog.as_ref() else {
                    return Vec::new();
                };
                for skill in catalog {
                    let name = skill.name.to_lowercase();
                    let description = skill.description.to_lowercase();
                    let matches = if query.is_empty() {
                        1
                    } else if name == query {
                        3
                    } else if name.starts_with(&query) {
                        2
                    } else if name.contains(&query)
                        || description.contains(&query)
                        || skill.source.to_lowercase().contains(&query)
                    {
                        1
                    } else {
                        0
                    };
                    if matches == 0 {
                        continue;
                    }

                    let active = self.selected_skills.iter().any(|item| item == &skill.name);
                    let item = command_popup::CommandMatch {
                        command: skill.name.clone(),
                        description: format!(
                            "{}{}",
                            skill.source,
                            if active { "  •  active" } else { "" }
                        ),
                        preview_lines: vec![
                            format!("source: {}", skill.source),
                            format!(
                                "description: {}",
                                if skill.description.trim().is_empty() {
                                    "(none)"
                                } else {
                                    skill.description.trim()
                                }
                            ),
                            if active {
                                "status: already active".to_string()
                            } else {
                                "status: ready to add".to_string()
                            },
                        ],
                        autocomplete: format!("/skill add {}", skill.name),
                        action: command_popup::PopupAction::EnableSkill(skill.name.clone()),
                    };
                    match matches {
                        3 => exact.push(item),
                        2 => prefix.push(item),
                        _ => contains.push(item),
                    }
                }
            }
            SkillPopupMode::Remove => {
                let selected = self
                    .selected_skills
                    .iter()
                    .map(|name| {
                        let details = self
                            .skill_catalog
                            .as_ref()
                            .and_then(|catalog| catalog.iter().find(|item| item.name == *name));
                        (
                            name.clone(),
                            details
                                .map(|item| item.description.clone())
                                .unwrap_or_default(),
                            details
                                .map(|item| item.source.clone())
                                .unwrap_or_else(|| "selected".to_string()),
                        )
                    })
                    .collect::<Vec<_>>();
                for (name, description, source) in selected {
                    let lowered = name.to_lowercase();
                    let matches = if query.is_empty() {
                        1
                    } else if lowered == query {
                        3
                    } else if lowered.starts_with(&query) {
                        2
                    } else if lowered.contains(&query)
                        || description.to_lowercase().contains(&query)
                        || source.to_lowercase().contains(&query)
                    {
                        1
                    } else {
                        0
                    };
                    if matches == 0 {
                        continue;
                    }

                    let item = command_popup::CommandMatch {
                        command: name.clone(),
                        description: format!("{source}  •  active"),
                        preview_lines: vec![
                            format!("source: {source}"),
                            format!(
                                "description: {}",
                                if description.trim().is_empty() {
                                    "(none)"
                                } else {
                                    description.trim()
                                }
                            ),
                            "status: will be removed".to_string(),
                        ],
                        autocomplete: format!("/skill remove {name}"),
                        action: command_popup::PopupAction::DisableSkill(name),
                    };
                    match matches {
                        3 => exact.push(item),
                        2 => prefix.push(item),
                        _ => contains.push(item),
                    }
                }
            }
        }

        exact.extend(prefix);
        exact.extend(contains);
        exact
    }
}
