use crate::app::{AgentCandidate, AgentPopupMode, App};
use crate::bottom_pane::command_popup;

impl App {
    pub fn set_agent_catalog(&mut self, agents: Vec<(String, String, String, bool, String)>) {
        self.agent_catalog = Some(
            agents
                .into_iter()
                .map(
                    |(id, name, agent_mode, is_default, updated_at)| AgentCandidate {
                        id,
                        name,
                        agent_mode,
                        is_default,
                        updated_at,
                    },
                )
                .collect(),
        );
        self.sync_slash_popup_selection();
    }

    pub fn clear_agent_catalog(&mut self) {
        self.agent_catalog = None;
    }

    pub(super) fn agent_popup_context(&self) -> Option<(AgentPopupMode, &str)> {
        let line = self.input.lines().next().unwrap_or("");
        if let Some(query) = line.strip_prefix("/agent set ") {
            if query.split_whitespace().count() <= 1 {
                return Some((AgentPopupMode::Set, query.trim()));
            }
        }
        None
    }

    pub(super) fn agent_popup_matches(
        &self,
        mode: AgentPopupMode,
        query: &str,
    ) -> Vec<command_popup::CommandMatch> {
        let Some(catalog) = self.agent_catalog.as_ref() else {
            return Vec::new();
        };

        let query = query.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        let mut contains = Vec::new();

        for agent in catalog {
            let id = agent.id.to_lowercase();
            let name = agent.name.to_lowercase();
            let matches = if query.is_empty() {
                1
            } else if id == query || name == query {
                3
            } else if id.starts_with(&query) || name.starts_with(&query) {
                2
            } else if id.contains(&query)
                || name.contains(&query)
                || agent.agent_mode.to_lowercase().contains(&query)
            {
                1
            } else {
                0
            };
            if matches == 0 {
                continue;
            }

            let item = command_popup::CommandMatch {
                command: agent.id.clone(),
                description: format!(
                    "{}  •  {}{}",
                    agent.name,
                    agent.agent_mode,
                    if agent.is_default {
                        "  •  default"
                    } else {
                        ""
                    }
                ),
                preview_lines: vec![
                    format!("name: {}", agent.name),
                    format!("mode: {}", agent.agent_mode),
                    format!("updated: {}", agent.updated_at),
                ],
                autocomplete: match mode {
                    AgentPopupMode::Set => format!("/agent set {}", agent.id),
                },
                action: command_popup::PopupAction::HandleCommand(match mode {
                    AgentPopupMode::Set => format!("/agent set {}", agent.id),
                }),
            };
            match matches {
                3 => exact.push(item),
                2 => prefix.push(item),
                _ => contains.push(item),
            }
        }

        exact.extend(prefix);
        exact.extend(contains);
        exact
    }
}
