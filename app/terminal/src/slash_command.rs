#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SlashCommandDef {
    pub(crate) command: &'static str,
    pub(crate) description: &'static str,
    pub(crate) usage: &'static str,
    pub(crate) example: &'static str,
}

impl SlashCommandDef {
    pub(crate) fn category(&self) -> &'static str {
        match self.command {
            "/new" | "/clear" | "/sessions" | "/resume" | "/transcript" | "/welcome" | "/exit" => {
                "Session"
            }
            "/agent" | "/mode" | "/workspace" | "/sandbox" | "/model" | "/display" | "/goal" => {
                "Runtime"
            }
            "/skills" | "/skill" | "/config" | "/doctor" | "/providers" | "/provider" => "Setup",
            "/interrupt" | "/retry" | "/approve" | "/deny" | "/status" | "/approvals" => "Control",
            _ => "Help",
        }
    }

    pub(crate) fn detail_lines(&self) -> &'static [&'static str] {
        match self.command {
            "/agent" => &[
                "Use an agent id for a saved backend agent, or an agent config path for a local config file.",
                "Setting an agent config clears the explicit agent id; clearing returns to the runtime default.",
                "Coding configs usually need a repo workspace set with /workspace set <path>.",
            ],
            "/workspace" => &[
                "Controls the repo or directory the backend should use for future requests.",
                "Changing the workspace refreshes workspace-scoped skills and affects new backend work.",
                "Use /workspace clear to return to the default Sage workspace.",
            ],
            "/sandbox" => &[
                "Controls the sandbox mode passed to the backend for future requests.",
                "local uses the local sandbox provider with workspace path checks; remote asks the remote sandbox provider; passthrough uses direct backend workspace access.",
                "Changing sandbox mode marks the backend for restart before the next task.",
                "Run /sandbox show for the effective mode, workspace, restart state, and next-step guidance.",
            ],
            "/display" => &[
                "compact hides internal tool and phase detail from the transcript.",
                "verbose keeps more backend detail visible for debugging.",
            ],
            "/goal" => &[
                "Use /goal <objective> to set the goal and immediately run it as a task.",
                "/goal set only updates local goal state; /goal done marks the current goal complete locally.",
            ],
            "/status" => &[
                "Shows the current session, runtime selection, workspace, sandbox, display mode, and goal state.",
                "Use this when the footer is too narrow to show all active runtime context.",
            ],
            "/approvals" => &[
                "Shows recent sandbox approval requests and runtime decisions for this terminal session.",
                "Use this to verify which command was approved, denied, or is still pending.",
            ],
            "/help" => &[
                "Open /help for the command list, or /help <command> for focused usage notes.",
            ],
            "/provider" => &[
                "Use provider commands to inspect, verify, create, update, delete, or switch defaults.",
                "Run /provider help for the full provider field reference.",
            ],
            "/skills" | "/skill" => &[
                "Skills are selected per terminal session and sent to the backend with future tasks.",
            ],
            "/interrupt" => &["Stops the active backend request while keeping any partial output visible."],
            "/retry" => &["Resubmits the last task with the current runtime selections."],
            "/approve" => &["Approves the pending sandbox command once."],
            "/deny" => &["Denies the pending sandbox command."],
            _ => &[],
        }
    }
}

const COMMANDS: [SlashCommandDef; 27] = [
    SlashCommandDef {
        command: "/help",
        description: "Show available commands",
        usage: "/help [command]",
        example: "/help provider",
    },
    SlashCommandDef {
        command: "/new",
        description: "Create a new local session",
        usage: "/new",
        example: "/new",
    },
    SlashCommandDef {
        command: "/clear",
        description: "Clear the current transcript",
        usage: "/clear",
        example: "/clear",
    },
    SlashCommandDef {
        command: "/sessions",
        description: "List recent local sessions",
        usage: "/sessions [positive_limit] | /sessions inspect <latest|session_id>",
        example: "/sessions inspect latest",
    },
    SlashCommandDef {
        command: "/resume",
        description: "Resume latest or a specific session",
        usage: "/resume [latest|session_id]",
        example: "/resume local-000123",
    },
    SlashCommandDef {
        command: "/skills",
        description: "List visible skills and active selection",
        usage: "/skills",
        example: "/skills",
    },
    SlashCommandDef {
        command: "/skill",
        description: "Add/remove/clear selected skills",
        usage: "/skill add <name> | /skill remove <name> | /skill clear",
        example: "/skill add github",
    },
    SlashCommandDef {
        command: "/config",
        description: "Show effective CLI config",
        usage: "/config | /config init [path] [--force]",
        example: "/config init --force",
    },
    SlashCommandDef {
        command: "/doctor",
        description: "Show CLI/runtime diagnostics",
        usage: "/doctor [probe-provider]",
        example: "/doctor probe-provider",
    },
    SlashCommandDef {
        command: "/providers",
        description: "List configured providers",
        usage: "/providers",
        example: "/providers",
    },
    SlashCommandDef {
        command: "/provider",
        description: "Inspect or switch the default provider",
        usage: "/provider | /provider help | /provider inspect <id> | /provider verify [key=value...] | /provider default <id> | /provider create key=value... | /provider update <id> key=value... | /provider delete <id>",
        example: "/provider create name=openai model=gpt-5 base=https://api.openai.com/v1",
    },
    SlashCommandDef {
        command: "/model",
        description: "Show or override the current model",
        usage: "/model | /model show | /model set <name> | /model clear",
        example: "/model set gpt-5",
    },
    SlashCommandDef {
        command: "/agent",
        description: "Show or override the current agent or config",
        usage: "/agent | /agent show | /agent list | /agent set <agent_id> | /agent config <path|coding> | /agent clear",
        example: "/agent config coding",
    },
    SlashCommandDef {
        command: "/mode",
        description: "Show or override the current agent mode",
        usage: "/mode | /mode show | /mode set <simple|multi|fibre>",
        example: "/mode set fibre",
    },
    SlashCommandDef {
        command: "/display",
        description: "Switch transcript detail level",
        usage: "/display | /display show | /display set <compact|verbose>",
        example: "/display set verbose",
    },
    SlashCommandDef {
        command: "/workspace",
        description: "Show or override the current workspace",
        usage: "/workspace | /workspace show | /workspace set <path> | /workspace clear",
        example: "/workspace set /tmp/project",
    },
    SlashCommandDef {
        command: "/sandbox",
        description: "Show or override sandbox type and approval mode",
        usage: "/sandbox | /sandbox show | /sandbox set <local|remote|passthrough> | /sandbox approval set <untrusted|on-request|never> | /sandbox clear",
        example: "/sandbox approval set untrusted",
    },
    SlashCommandDef {
        command: "/goal",
        description: "Show the current goal, or set and run a new goal",
        usage: "/goal | /goal <objective> | /goal show | /goal set <objective> | /goal clear | /goal done",
        example: "/goal ship the terminal goal MVP",
    },
    SlashCommandDef {
        command: "/interrupt",
        description: "Interrupt the active request",
        usage: "/interrupt",
        example: "/interrupt",
    },
    SlashCommandDef {
        command: "/retry",
        description: "Retry the last submitted task",
        usage: "/retry",
        example: "/retry",
    },
    SlashCommandDef {
        command: "/approve",
        description: "Approve the pending sandbox command once",
        usage: "/approve",
        example: "/approve",
    },
    SlashCommandDef {
        command: "/deny",
        description: "Deny the pending sandbox command",
        usage: "/deny",
        example: "/deny",
    },
    SlashCommandDef {
        command: "/status",
        description: "Show current session state",
        usage: "/status",
        example: "/status",
    },
    SlashCommandDef {
        command: "/approvals",
        description: "Show recent sandbox approvals",
        usage: "/approvals",
        example: "/approvals",
    },
    SlashCommandDef {
        command: "/transcript",
        description: "Browse the in-app transcript overlay",
        usage: "/transcript",
        example: "/transcript",
    },
    SlashCommandDef {
        command: "/welcome",
        description: "Show the welcome banner again",
        usage: "/welcome",
        example: "/welcome",
    },
    SlashCommandDef {
        command: "/exit",
        description: "Exit Sage Terminal",
        usage: "/exit",
        example: "/exit",
    },
];

pub(crate) fn all() -> &'static [SlashCommandDef] {
    &COMMANDS
}

pub(crate) fn find(command: &str) -> Option<&'static SlashCommandDef> {
    let normalized = if command.starts_with('/') {
        command.to_string()
    } else {
        format!("/{command}")
    };
    COMMANDS.iter().find(|item| item.command == normalized)
}

#[cfg(test)]
mod tests {
    use super::{all, find};

    #[test]
    fn help_topics_accept_bare_or_slash_prefixed_command_names() {
        assert_eq!(find("provider").map(|item| item.command), Some("/provider"));
        assert_eq!(
            find("/provider").map(|item| item.command),
            Some("/provider")
        );
    }

    #[test]
    fn commands_keep_popup_presentation_order_stable() {
        let names = all().iter().map(|item| item.command).collect::<Vec<_>>();
        assert_eq!(names[..3], ["/help", "/new", "/clear"]);
    }
}
