use crate::display_policy::DisplayMode;

mod help;
mod parse;
#[cfg(test)]
mod tests;

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct StartupOptions {
    pub(crate) agent_id: Option<String>,
    pub(crate) agent_mode: Option<String>,
    pub(crate) display_mode: Option<DisplayMode>,
    pub(crate) workspace: Option<String>,
}

impl StartupOptions {
    pub(crate) fn with_fallbacks(self, defaults: StartupOptions) -> Self {
        Self {
            agent_id: self.agent_id.or(defaults.agent_id),
            agent_mode: self.agent_mode.or(defaults.agent_mode),
            display_mode: self.display_mode.or(defaults.display_mode),
            workspace: self.workspace.or(defaults.workspace),
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
