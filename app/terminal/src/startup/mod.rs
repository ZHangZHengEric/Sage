mod help;
mod parse;
#[cfg(test)]
mod tests;

#[derive(Debug)]
pub(crate) enum StartupBehavior {
    Run(Option<crate::app::SubmitAction>),
    PrintHelp,
}

pub(crate) use help::print_usage;
pub(crate) use parse::parse_startup_action;
