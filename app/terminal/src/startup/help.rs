pub(crate) fn print_usage() {
    println!("{}", usage_text());
}

pub(crate) fn usage_text() -> &'static str {
    "Usage:
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>]
  sage tui coding [--workspace <path>] [--display <compact|verbose>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] [prompt]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] run <prompt>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] chat <prompt>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] config init [path] [--force]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] doctor
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] doctor probe-provider
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] provider verify [key=value...]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] sessions
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] sessions <limit>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] sessions inspect <latest|session_id>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] resume
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] resume latest
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|fibre|team>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] [--runtime <v1|v2>] resume <session_id>"
}
