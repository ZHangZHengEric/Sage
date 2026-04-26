use crate::app::{App, ProviderCandidate, ProviderPopupMode};
use crate::bottom_pane::command_popup;

impl App {
    pub fn set_provider_catalog(
        &mut self,
        providers: Vec<(String, String, String, String, bool)>,
    ) {
        self.provider_catalog = Some(
            providers
                .into_iter()
                .map(
                    |(id, name, model, base_url, is_default)| ProviderCandidate {
                        id,
                        name,
                        model,
                        base_url,
                        is_default,
                    },
                )
                .collect(),
        );
        self.sync_slash_popup_selection();
    }

    pub fn clear_provider_catalog(&mut self) {
        self.provider_catalog = None;
    }

    pub(super) fn provider_popup_context(&self) -> Option<(ProviderPopupMode, &str)> {
        let line = self.input.lines().next().unwrap_or("");
        if let Some(query) = line.strip_prefix("/provider inspect ") {
            if query.split_whitespace().count() <= 1 {
                return Some((ProviderPopupMode::Inspect, query.trim()));
            }
        }
        if let Some(query) = line.strip_prefix("/provider default ") {
            if query.split_whitespace().count() <= 1 {
                return Some((ProviderPopupMode::Default, query.trim()));
            }
        }
        None
    }

    pub(super) fn provider_popup_matches(
        &self,
        mode: ProviderPopupMode,
        query: &str,
    ) -> Vec<command_popup::CommandMatch> {
        let Some(catalog) = self.provider_catalog.as_ref() else {
            return Vec::new();
        };

        let query = query.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        let mut contains = Vec::new();

        for provider in catalog {
            let id = provider.id.to_lowercase();
            let name = provider.name.to_lowercase();
            let matches = if query.is_empty() {
                1
            } else if id == query || name == query {
                3
            } else if id.starts_with(&query) || name.starts_with(&query) {
                2
            } else if id.contains(&query)
                || name.contains(&query)
                || provider.model.to_lowercase().contains(&query)
            {
                1
            } else {
                0
            };
            if matches == 0 {
                continue;
            }

            let description = format!(
                "{}  •  {}{}",
                provider.name,
                provider.model,
                if provider.is_default {
                    "  •  default"
                } else {
                    ""
                }
            );
            let action = match mode {
                ProviderPopupMode::Inspect => {
                    command_popup::PopupAction::ShowProvider(provider.id.clone())
                }
                ProviderPopupMode::Default => {
                    command_popup::PopupAction::SetDefaultProvider(provider.id.clone())
                }
            };
            let item = command_popup::CommandMatch {
                command: provider.id.clone(),
                description,
                preview_lines: vec![
                    format!("name: {}", provider.name),
                    format!("model: {}", provider.model),
                    format!("base: {}", provider.base_url),
                ],
                autocomplete: match mode {
                    ProviderPopupMode::Inspect => format!("/provider inspect {}", provider.id),
                    ProviderPopupMode::Default => format!("/provider default {}", provider.id),
                },
                action,
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
