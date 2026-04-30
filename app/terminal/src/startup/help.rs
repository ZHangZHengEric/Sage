pub(crate) fn print_usage() {
    println!("{}", usage_text());
}

pub(crate) fn usage_text() -> &'static str {
    "Usage:
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] run <prompt>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] chat <prompt>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] config init [path] [--force]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] doctor
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] doctor probe-provider
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] provider verify [key=value...]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] sessions
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] sessions <limit>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] sessions inspect <latest|session_id>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] resume
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] resume latest
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] resume <session_id>"
}
