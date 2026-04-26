use anyhow::{anyhow, Result};

use crate::app::{SessionPickerMode, SubmitAction};

#[derive(Debug)]
pub(crate) enum StartupBehavior {
    Run(Option<SubmitAction>),
    PrintHelp,
}

pub(crate) fn parse_startup_action(
    args: impl IntoIterator<Item = String>,
) -> Result<StartupBehavior> {
    let args = args.into_iter().collect::<Vec<_>>();
    match args.as_slice() {
        [] => Ok(StartupBehavior::Run(None)),
        [flag] if matches!(flag.as_str(), "-h" | "--help" | "help") => {
            Ok(StartupBehavior::PrintHelp)
        }
        [command, prompt @ ..] if matches!(command.as_str(), "run" | "chat") => {
            if prompt.is_empty() {
                return Err(anyhow!("{command} requires a prompt"));
            }
            Ok(StartupBehavior::Run(Some(SubmitAction::RunTask(
                prompt.join(" "),
            ))))
        }
        [command, subcommand, rest @ ..] if command == "config" && subcommand == "init" => {
            let (path, force) = parse_config_init_args(rest)?;
            Ok(StartupBehavior::Run(Some(SubmitAction::InitConfig {
                path,
                force,
            })))
        }
        [command] if command == "doctor" => {
            Ok(StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
                probe_provider: false,
            })))
        }
        [command, probe]
            if command == "doctor"
                && matches!(probe.as_str(), "probe-provider" | "--probe-provider") =>
        {
            Ok(StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
                probe_provider: true,
            })))
        }
        [command] if command == "sessions" => Ok(StartupBehavior::Run(Some(
            SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 10,
            },
        ))),
        [command, subcommand, target] if command == "sessions" && subcommand == "inspect" => {
            Ok(StartupBehavior::Run(Some(SubmitAction::ShowSession(
                target.clone(),
            ))))
        }
        [command, limit] if command == "sessions" => {
            let limit = limit
                .parse::<usize>()
                .map_err(|_| anyhow!("sessions limit must be a positive integer"))?;
            if limit == 0 {
                return Err(anyhow!("sessions limit must be a positive integer"));
            }
            Ok(StartupBehavior::Run(Some(
                SubmitAction::OpenSessionPicker {
                    mode: SessionPickerMode::Browse,
                    limit,
                },
            )))
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
        [command, subcommand, fields @ ..] if command == "provider" && subcommand == "verify" => {
            Ok(StartupBehavior::Run(Some(SubmitAction::VerifyProvider(
                fields.to_vec(),
            ))))
        }
        _ => Err(anyhow!(
            "unsupported arguments: {}\n\n{}",
            args.join(" "),
            usage_text()
        )),
    }
}

pub(crate) fn print_usage() {
    println!("{}", usage_text());
}

pub(crate) fn usage_text() -> &'static str {
    "Usage:
  sage-terminal
  sage-terminal run <prompt>
  sage-terminal chat <prompt>
  sage-terminal config init [path] [--force]
  sage-terminal doctor
  sage-terminal doctor probe-provider
  sage-terminal provider verify [key=value...]
  sage-terminal sessions
  sage-terminal sessions <limit>
  sage-terminal sessions inspect <latest|session_id>
  sage-terminal resume
  sage-terminal resume latest
  sage-terminal resume <session_id>"
}

fn parse_config_init_args(args: &[String]) -> Result<(Option<String>, bool)> {
    let mut path = None;
    let mut force = false;
    for arg in args {
        if arg == "--force" {
            force = true;
            continue;
        }
        if path.is_none() {
            path = Some(arg.clone());
            continue;
        }
        return Err(anyhow!(
            "config init accepts at most one path and optional --force"
        ));
    }
    Ok((path, force))
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
    fn parse_startup_action_supports_run_and_chat_prompts() {
        let run_action = parse_startup_action(vec![
            "run".to_string(),
            "inspect".to_string(),
            "repo".to_string(),
        ])
        .expect("parse");
        assert!(matches!(
            run_action,
            StartupBehavior::Run(Some(SubmitAction::RunTask(prompt)))
                if prompt == "inspect repo"
        ));

        let chat_action =
            parse_startup_action(vec!["chat".to_string(), "hello".to_string()]).expect("parse");
        assert!(matches!(
            chat_action,
            StartupBehavior::Run(Some(SubmitAction::RunTask(prompt)))
                if prompt == "hello"
        ));
    }

    #[test]
    fn parse_startup_action_supports_doctor() {
        let action = parse_startup_action(vec!["doctor".to_string()]).expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
                probe_provider: false
            }))
        ));

        let action = parse_startup_action(vec!["doctor".to_string(), "probe-provider".to_string()])
            .expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
                probe_provider: true
            }))
        ));

        let action =
            parse_startup_action(vec!["doctor".to_string(), "--probe-provider".to_string()])
                .expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
                probe_provider: true
            }))
        ));
    }

    #[test]
    fn parse_startup_action_supports_config_init() {
        let action =
            parse_startup_action(vec!["config".to_string(), "init".to_string()]).expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::InitConfig {
                path: None,
                force: false
            }))
        ));

        let action = parse_startup_action(vec![
            "config".to_string(),
            "init".to_string(),
            "/tmp/demo.env".to_string(),
            "--force".to_string(),
        ])
        .expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::InitConfig {
                path: Some(path),
                force: true
            })) if path == "/tmp/demo.env"
        ));
    }

    #[test]
    fn parse_startup_action_supports_provider_verify() {
        let action = parse_startup_action(vec![
            "provider".to_string(),
            "verify".to_string(),
            "name=demo".to_string(),
            "model=demo-chat".to_string(),
        ])
        .expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::VerifyProvider(fields)))
                if fields == vec!["name=demo".to_string(), "model=demo-chat".to_string()]
        ));
    }

    #[test]
    fn parse_startup_action_supports_sessions_picker() {
        let action = parse_startup_action(vec!["sessions".to_string()]).expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 10
            }))
        ));

        let action =
            parse_startup_action(vec!["sessions".to_string(), "25".to_string()]).expect("parse");
        assert!(matches!(
            action,
            StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 25
            }))
        ));
    }

    #[test]
    fn parse_startup_action_supports_sessions_inspect() {
        let latest = parse_startup_action(vec![
            "sessions".to_string(),
            "inspect".to_string(),
            "latest".to_string(),
        ])
        .expect("parse");
        assert!(matches!(
            latest,
            StartupBehavior::Run(Some(SubmitAction::ShowSession(session_id)))
                if session_id == "latest"
        ));

        let specific = parse_startup_action(vec![
            "sessions".to_string(),
            "inspect".to_string(),
            "local-000123".to_string(),
        ])
        .expect("parse");
        assert!(matches!(
            specific,
            StartupBehavior::Run(Some(SubmitAction::ShowSession(session_id)))
                if session_id == "local-000123"
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
        let err = parse_startup_action(vec!["unknown".to_string()]).expect_err("should fail");
        assert!(err.to_string().contains("unsupported arguments"));
    }

    #[test]
    fn parse_startup_action_rejects_invalid_sessions_limit() {
        let err = parse_startup_action(vec!["sessions".to_string(), "0".to_string()])
            .expect_err("should fail");
        assert!(err.to_string().contains("positive integer"));
    }

    #[test]
    fn parse_startup_action_rejects_missing_run_prompt() {
        let err = parse_startup_action(vec!["run".to_string()]).expect_err("should fail");
        assert!(err.to_string().contains("requires a prompt"));
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
