pub(crate) fn print_usage() {
    println!("{}", usage_text());
}

pub(crate) fn usage_text() -> &'static str {
    "Usage:
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] run <prompt>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] chat <prompt>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] config init [path] [--force]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] doctor
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] doctor probe-provider
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] provider verify [key=value...]
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] sessions
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] sessions <limit>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] sessions inspect <latest|session_id>
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] resume
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] resume latest
  sage-terminal [--agent-id <id>] [--agent-mode <simple|multi|fibre>] [--display <compact|verbose>] [--workspace <path>] resume <session_id>"
}
