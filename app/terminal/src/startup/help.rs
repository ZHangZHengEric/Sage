pub(crate) fn print_usage() {
    println!("{}", usage_text());
}

pub(crate) fn usage_text() -> &'static str {
    "Usage:
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>]
  sage tui coding [--workspace <path>] [--display <compact|verbose>] [--sandbox-type <local|remote|passthrough>] [prompt]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] run <prompt>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] chat <prompt>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] config init [path] [--force]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] doctor
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] doctor probe-provider
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] provider verify [key=value...]
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] sessions
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] sessions <limit>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] sessions inspect <latest|session_id>
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] resume
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] resume latest
  sage tui [--agent-id <id>] [--agent-config <path|coding>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] [--sandbox-type <local|remote|passthrough>] resume <session_id>"
}
