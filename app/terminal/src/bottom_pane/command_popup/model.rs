#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandMatch {
    pub(crate) command: String,
    pub(crate) description: String,
    pub(crate) preview_lines: Vec<String>,
    pub(crate) autocomplete: String,
    pub(crate) action: PopupAction,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum PopupAction {
    HandleCommand(String),
    ShowProvider(String),
    SetDefaultProvider(String),
    EnableSkill(String),
    DisableSkill(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandPopupProps {
    pub(crate) items: Vec<CommandPopupItem>,
    pub(crate) window_status: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CommandPopupItem {
    pub(crate) command: String,
    pub(crate) description: String,
    pub(crate) preview_lines: Vec<String>,
    pub(crate) selected: bool,
}
