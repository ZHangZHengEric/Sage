mod app;
mod app_preview;
mod app_render;
mod backend;
mod bottom_pane;
mod custom_terminal;
mod history;
mod markdown;
mod slash_command;
mod startup;
mod terminal;
mod terminal_layout;
mod terminal_support;
mod ui;
mod ui_support;
mod wrap;

use std::env;
use std::path::PathBuf;

use anyhow::Result;
use app::App;
use startup::{parse_startup_action, print_usage, StartupBehavior};
use terminal::{restore_terminal, run, run_with_startup_action, setup_terminal};

fn main() -> Result<()> {
    let (startup_action, startup_options) = match parse_startup_action(env::args().skip(1))? {
        StartupBehavior::Run { action, options } => (action, options),
        StartupBehavior::PrintHelp => {
            print_usage();
            return Ok(());
        }
    };
    let mut app = App::new();
    app.apply_startup_agent_options(
        startup_options.agent_id,
        startup_options.agent_mode,
        startup_options.workspace.map(PathBuf::from),
    );
    let mut terminal = setup_terminal(&app)?;
    let result = match startup_action {
        Some(action) => run_with_startup_action(&mut terminal, &mut app, Some(action)),
        None => run(&mut terminal, &mut app),
    };
    restore_terminal(&mut terminal)?;
    result
}
