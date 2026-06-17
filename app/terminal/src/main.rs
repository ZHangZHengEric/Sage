mod app;
mod app_preview;
mod app_render;
mod backend;
mod bottom_pane;
mod custom_terminal;
mod display_policy;
mod history;
mod markdown;
mod preferences;
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
use preferences::{load_next_local_session_sequence, load_startup_preferences};
use startup::{parse_startup_action, print_usage, StartupBehavior};
use terminal::{restore_terminal, run, run_with_startup_action, setup_terminal, AppTerminal};

fn main() -> Result<()> {
    let (startup_action, startup_options) = match parse_startup_action(env::args().skip(1))? {
        StartupBehavior::Run { action, options } => (action, options),
        StartupBehavior::PrintHelp => {
            print_usage();
            return Ok(());
        }
    };
    let startup_options =
        startup_options.with_fallbacks(load_startup_preferences().unwrap_or_else(|err| {
            eprintln!("warning: failed to load terminal preferences: {err}");
            startup::StartupOptions::default()
        }));
    let session_seq = load_next_local_session_sequence().unwrap_or_else(|err| {
        eprintln!("warning: failed to resolve next local session sequence: {err}");
        1
    });
    let mut app = App::new_with_session_seq(session_seq);
    app.apply_startup_options(
        startup_options.agent_id,
        startup_options.agent_config.map(PathBuf::from),
        startup_options.agent_mode,
        startup_options.display_mode,
        startup_options.workspace.map(PathBuf::from),
        startup_options.sandbox_type,
    );
    let terminal = setup_terminal(&app)?;
    let mut terminal_guard = TerminalRestoreGuard::new(terminal);
    let result = match startup_action {
        Some(action) => {
            run_with_startup_action(terminal_guard.terminal_mut(), &mut app, Some(action))
        }
        None => run(terminal_guard.terminal_mut(), &mut app),
    };
    terminal_guard.restore()?;
    result
}

struct TerminalRestoreGuard {
    terminal: Option<AppTerminal>,
}

impl TerminalRestoreGuard {
    fn new(terminal: AppTerminal) -> Self {
        Self {
            terminal: Some(terminal),
        }
    }

    fn terminal_mut(&mut self) -> &mut AppTerminal {
        self.terminal
            .as_mut()
            .expect("terminal should exist until restored")
    }

    fn restore(&mut self) -> Result<()> {
        if let Some(mut terminal) = self.terminal.take() {
            restore_terminal(&mut terminal)?;
        }
        Ok(())
    }
}

impl Drop for TerminalRestoreGuard {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}
