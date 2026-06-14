#[path = "command_popup/matching.rs"]
mod matching;
#[path = "command_popup/model.rs"]
mod model;
#[path = "command_popup/render.rs"]
mod render;
#[cfg(test)]
#[path = "command_popup/tests.rs"]
mod tests;

pub(crate) use matching::{
    matching_commands, popup_query, props_from_matches, props_from_matches_for_rows,
};
pub(crate) use model::{CommandMatch, CommandPopupProps, PopupAction};
pub(crate) use render::{popup_height, render};
