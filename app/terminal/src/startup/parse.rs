use anyhow::{anyhow, Result};

use crate::app::{normalize_agent_mode, SessionPickerMode, SubmitAction};

use super::StartupOptions;
use super::help::usage_text;
use super::StartupBehavior;

pub(crate) fn parse_startup_action(
    args: impl IntoIterator<Item = String>,
) -> Result<StartupBehavior> {
    let args = args.into_iter().collect::<Vec<_>>();
    let (options, args) = parse_global_options(&args)?;
    match args.as_slice() {
        [] => Ok(StartupBehavior::Run {
            action: None,
            options,
        }),
        [flag] if matches!(flag.as_str(), "-h" | "--help" | "help") => {
            Ok(StartupBehavior::PrintHelp)
        }
        [command, prompt @ ..] if matches!(command.as_str(), "run" | "chat") => {
            if prompt.is_empty() {
                return Err(anyhow!("{command} requires a prompt"));
            }
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::RunTask(prompt.join(" "))),
                options,
            })
        }
        [command, subcommand, rest @ ..] if command == "config" && subcommand == "init" => {
            let (path, force) = parse_config_init_args(rest)?;
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::InitConfig { path, force }),
                options,
            })
        }
        [command] if command == "doctor" => Ok(StartupBehavior::Run {
            action: Some(SubmitAction::ShowDoctor {
                probe_provider: false,
            }),
            options,
        }),
        [command, probe]
            if command == "doctor"
                && matches!(probe.as_str(), "probe-provider" | "--probe-provider") =>
        {
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::ShowDoctor {
                    probe_provider: true,
                }),
                options,
            })
        }
        [command] if command == "sessions" => Ok(StartupBehavior::Run {
            action: Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 10,
            }),
            options,
        }),
        [command, subcommand, target] if command == "sessions" && subcommand == "inspect" => Ok(
            StartupBehavior::Run {
                action: Some(SubmitAction::ShowSession(target.clone())),
                options,
            },
        ),
        [command, limit] if command == "sessions" => {
            let limit = limit
                .parse::<usize>()
                .map_err(|_| anyhow!("sessions limit must be a positive integer"))?;
            if limit == 0 {
                return Err(anyhow!("sessions limit must be a positive integer"));
            }
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::OpenSessionPicker {
                    mode: SessionPickerMode::Browse,
                    limit,
                }),
                options,
            })
        }
        [command] if command == "resume" => Ok(StartupBehavior::Run {
            action: Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Resume,
                limit: 10,
            }),
            options,
        }),
        [command, target] if command == "resume" && target == "latest" => {
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::ResumeLatest),
                options,
            })
        }
        [command, session_id] if command == "resume" => Ok(StartupBehavior::Run {
            action: Some(SubmitAction::ResumeSession(session_id.clone())),
            options,
        }),
        [command, subcommand, fields @ ..] if command == "provider" && subcommand == "verify" => {
            Ok(StartupBehavior::Run {
                action: Some(SubmitAction::VerifyProvider(fields.to_vec())),
                options,
            })
        }
        _ => Err(anyhow!(
            "unsupported arguments: {}\n\n{}",
            args.join(" "),
            usage_text()
        )),
    }
}

fn parse_global_options(args: &[String]) -> Result<(StartupOptions, Vec<String>)> {
    let mut options = StartupOptions::default();
    let mut idx = 0;
    while idx < args.len() {
        match args[idx].as_str() {
            "--agent-id" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| anyhow!("--agent-id requires a value"))?;
                options.agent_id = Some(value.clone());
                idx += 2;
            }
            "--agent-mode" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| anyhow!("--agent-mode requires a value"))?;
                options.agent_mode = Some(
                    normalize_agent_mode(value).ok_or_else(|| {
                        anyhow!("--agent-mode must be one of: simple, multi, fibre")
                    })?,
                );
                idx += 2;
            }
            _ => break,
        }
    }
    Ok((options, args[idx..].to_vec()))
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
