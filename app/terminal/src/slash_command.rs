#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SlashCommandDef {
    pub(crate) command: &'static str,
    pub(crate) description: &'static str,
    pub(crate) usage: &'static str,
    pub(crate) example: &'static str,
}

const COMMANDS: [SlashCommandDef; 18] = [
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
        description: "Show or override the current agent",
        usage: "/agent | /agent show | /agent list | /agent set <agent_id> | /agent clear",
        example: "/agent set agent_demo",
    },
    SlashCommandDef {
        command: "/mode",
        description: "Show or override the current agent mode",
        usage: "/mode | /mode show | /mode set <simple|multi|fibre>",
        example: "/mode set fibre",
    },
    SlashCommandDef {
        command: "/status",
        description: "Show current session state",
        usage: "/status",
        example: "/status",
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
