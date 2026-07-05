use crate::display_policy::DisplayMode;

mod help;
mod parse;
#[cfg(test)]
mod tests;

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct StartupOptions {
    pub(crate) agent_id: Option<String>,
    pub(crate) agent_config: Option<String>,
    pub(crate) agent_mode: Option<String>,
    pub(crate) display_mode: Option<DisplayMode>,
    pub(crate) workspace: Option<String>,
    pub(crate) sandbox_type: Option<String>,
    pub(crate) sandbox_approval_mode: Option<String>,
}

impl StartupOptions {
    pub(crate) fn with_fallbacks(self, defaults: StartupOptions) -> Self {
        let agent_config = self.agent_config.or(defaults.agent_config);
        let has_agent_config = agent_config.is_some();
        Self {
            agent_id: if has_agent_config {
                None
            } else {
                self.agent_id.or(defaults.agent_id)
            },
            agent_config,
            agent_mode: if has_agent_config {
                self.agent_mode
            } else {
                self.agent_mode.or(defaults.agent_mode)
            },
            display_mode: self.display_mode.or(defaults.display_mode),
            workspace: self.workspace.or(defaults.workspace),
            sandbox_type: self.sandbox_type.or(defaults.sandbox_type),
            sandbox_approval_mode: self
                .sandbox_approval_mode
                .or(defaults.sandbox_approval_mode),
        }
    }
}

#[derive(Debug)]
pub(crate) enum StartupBehavior {
    Run {
        action: Option<crate::app::SubmitAction>,
        options: StartupOptions,
    },
    PrintHelp,
}

pub(crate) use help::print_usage;
pub(crate) use parse::parse_startup_action;
