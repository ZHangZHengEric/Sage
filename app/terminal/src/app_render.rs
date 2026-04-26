#[path = "app_render/assistant.rs"]
mod assistant;
#[path = "app_render/common.rs"]
mod common;
#[path = "app_render/messages.rs"]
mod messages;
#[path = "app_render/welcome.rs"]
mod welcome;

pub(crate) use messages::{format_message, format_message_continuation};
#[cfg(test)]
pub(crate) use assistant::render_assistant_body;
pub(crate) use welcome::welcome_lines;
