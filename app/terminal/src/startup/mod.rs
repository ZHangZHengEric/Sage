mod help;
mod parse;
#[cfg(test)]
mod tests;

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct StartupOptions {
    pub(crate) agent_id: Option<String>,
    pub(crate) agent_mode: Option<String>,
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
