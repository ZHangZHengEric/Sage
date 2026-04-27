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
