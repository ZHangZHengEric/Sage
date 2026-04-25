mod app;
mod app_preview;
mod app_render;
mod backend;
mod backend_support;
mod bottom_pane;
mod custom_terminal;
mod history;
mod markdown;
mod slash_command;
mod terminal;
mod terminal_layout;
mod terminal_support;
mod ui;
mod wrap;

use std::env;

use anyhow::{anyhow, Result};
use app::{App, SessionPickerMode, SubmitAction};
use terminal::{restore_terminal, run, run_with_startup_action, setup_terminal};

fn main() -> Result<()> {
    let startup_action = match parse_startup_action(env::args().skip(1))? {
        StartupBehavior::Run(action) => action,
        StartupBehavior::PrintHelp => {
            print_usage();
            return Ok(());
        }
    };
    let mut app = App::new();
    let mut terminal = setup_terminal(&app)?;
    let result = match startup_action {
        Some(action) => run_with_startup_action(&mut terminal, &mut app, Some(action)),
        None => run(&mut terminal, &mut app),
    };
    restore_terminal(&mut terminal)?;
    result
}

#[derive(Debug)]
enum StartupBehavior {
    Run(Option<SubmitAction>),
    PrintHelp,
}

fn parse_startup_action(args: impl IntoIterator<Item = String>) -> Result<StartupBehavior> {
    let args = args.into_iter().collect::<Vec<_>>();
    match args.as_slice() {
        [] => Ok(StartupBehavior::Run(None)),
        [flag] if matches!(flag.as_str(), "-h" | "--help" | "help") => {
            Ok(StartupBehavior::PrintHelp)
        }
        [command] if command == "resume" => Ok(StartupBehavior::Run(Some(
            SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Resume,
                limit: 10,
            },
        ))),
        [command, target] if command == "resume" && target == "latest" => {
            Ok(StartupBehavior::Run(Some(SubmitAction::ResumeLatest)))
        }
        [command, session_id] if command == "resume" => Ok(StartupBehavior::Run(Some(
            SubmitAction::ResumeSession(session_id.clone()),
        ))),
        _ => Err(anyhow!(
            "unsupported arguments: {}\n\n{}",
            args.join(" "),
            usage_text()
        )),
    }
}

fn print_usage() {
    println!("{}", usage_text());
}

fn usage_text() -> &'static str {
    "Usage:
  sage-terminal
  sage-terminal resume
  sage-terminal resume latest
  sage-terminal resume <session_id>"
}

#[cfg(test)]
mod tests {
    use super::{parse_startup_action, StartupBehavior};
    use crate::app::{SessionPickerMode, SubmitAction};

    #[test]
    fn parse_startup_action_defaults_to_plain_tui() {
        assert!(parse_startup_action(Vec::<String>::new())
            .expect("parse")
            .matches_run_none());
    }

    #[test]
    fn parse_startup_action_supports_resume_picker() {
        let action = parse_startup_action(vec!["resume".to_string()]).expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Resume,
                limit: 10
            }))
        ));
    }

    #[test]
    fn parse_startup_action_supports_resume_targets() {
        let latest =
            parse_startup_action(vec!["resume".to_string(), "latest".to_string()]).expect("parse");
        assert!(matches!(
            latest,
            StartupBehavior::Run(Some(SubmitAction::ResumeLatest))
        ));

        let specific = parse_startup_action(vec!["resume".to_string(), "local-000123".to_string()])
            .expect("parse");
        assert!(matches!(
            specific,
            StartupBehavior::Run(Some(SubmitAction::ResumeSession(session_id)))
                if session_id == "local-000123"
        ));
    }

    #[test]
    fn parse_startup_action_rejects_unknown_commands() {
        let err = parse_startup_action(vec!["sessions".to_string()]).expect_err("should fail");
        assert!(err.to_string().contains("unsupported arguments"));
    }

    #[test]
    fn parse_startup_action_supports_help_flag() {
        let action = parse_startup_action(vec!["--help".to_string()]).expect("parse");
        assert!(matches!(action, StartupBehavior::PrintHelp));
    }

    impl StartupBehavior {
        fn matches_run_none(&self) -> bool {
            matches!(self, StartupBehavior::Run(None))
        }
    }
}
