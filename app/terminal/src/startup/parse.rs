use anyhow::{anyhow, Result};

use crate::app::{SessionPickerMode, SubmitAction};

use super::help::usage_text;
use super::StartupBehavior;

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
        [command, subcommand, target] if command == "sessions" && subcommand == "inspect" => Ok(
            StartupBehavior::Run(Some(SubmitAction::ShowSession(target.clone()))),
        ),
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
