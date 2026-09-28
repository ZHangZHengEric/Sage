use crate::app::App;
use crate::bottom_pane::help_overlay;
use crate::slash_command;

impl App {
    pub fn help_overlay_props(&self) -> Option<help_overlay::HelpOverlayProps> {
        if !self.help_overlay_visible {
            return None;
        }
        let (title, sections) = match self.help_overlay_topic.as_deref() {
            Some(topic) => {
                let command = slash_command::find(topic)?;
                let mut sections = vec![
                    help_overlay::HelpSection {
                        title: "Command".to_string(),
                        items: vec![
                            help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            },
                            help_overlay::HelpItem {
                                label: "category".to_string(),
                                value: command.category().to_string(),
                            },
                        ],
                    },
                    help_overlay::HelpSection {
                        title: "Usage".to_string(),
                        items: vec![help_overlay::HelpItem {
                            label: String::new(),
                            value: command.usage.to_string(),
                        }],
                    },
                    help_overlay::HelpSection {
                        title: "Example".to_string(),
                        items: vec![help_overlay::HelpItem {
                            label: String::new(),
                            value: command.example.to_string(),
                        }],
                    },
                ];
                let detail_lines = command.detail_lines();
                if !detail_lines.is_empty() {
                    sections.push(help_overlay::HelpSection {
                        title: "Notes".to_string(),
                        items: detail_lines
                            .iter()
                            .map(|line| help_overlay::HelpItem {
                                label: String::new(),
                                value: (*line).to_string(),
                            })
                            .collect(),
                    });
                }
                (format!("Help  {}", command.command), sections)
            }
            None => (
                "Sage Terminal Help".to_string(),
                vec![
                    help_overlay::HelpSection {
                        title: "Help".to_string(),
                        items: slash_command::all()
                            .iter()
                            .filter(|command| command.category() == "Help")
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Session".to_string(),
                        items: slash_command::all()
                            .iter()
                            .filter(|command| command.category() == "Session")
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Runtime".to_string(),
                        items: slash_command::all()
                            .iter()
                            .filter(|command| command.category() == "Runtime")
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Setup".to_string(),
                        items: slash_command::all()
                            .iter()
                            .filter(|command| command.category() == "Setup")
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Control".to_string(),
                        items: slash_command::all()
                            .iter()
                            .filter(|command| command.category() == "Control")
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Navigation".to_string(),
                        items: vec![
                            help_overlay::HelpItem {
                                label: "popup".to_string(),
                                value: "↑/↓ select, tab complete, enter apply".to_string(),
                            },
                            help_overlay::HelpItem {
                                label: "overlay".to_string(),
                                value: "esc closes the current surface".to_string(),
                            },
                        ],
                    },
                    help_overlay::HelpSection {
                        title: "Tips".to_string(),
                        items: vec![help_overlay::HelpItem {
                            label: String::new(),
                            value: "Use /help <command> for focused usage notes.".to_string(),
                        }],
                    },
                ],
            ),
        };
        Some(help_overlay::HelpOverlayProps {
            title,
            sections,
            footer_hint: "esc or enter to close".to_string(),
        })
    }

    pub fn close_help_overlay(&mut self) -> bool {
        if !self.help_overlay_visible {
            return false;
        }
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }
}
