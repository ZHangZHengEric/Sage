use anyhow::Result;

use crate::app::{App, MessageKind};
use crate::backend::list_agents as fetch_agents;
use crate::terminal_support::format_agents_list;

pub(super) fn list_agents(app: &mut App) -> Result<bool> {
    match fetch_agents(&app.user_id) {
        Ok(agents) => {
            app.set_agent_catalog(
                agents
                    .iter()
                    .map(|agent| {
                        (
                            agent.agent_id.clone(),
                            agent.name.clone(),
                            agent.agent_mode.clone(),
                            agent.is_default,
                            agent.updated_at.clone(),
                        )
                    })
                    .collect(),
            );
            app.push_message(
                MessageKind::Tool,
                format_agents_list(&agents, app.selected_agent_id.as_deref()),
            );
            app.set_status(format!("agents  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(MessageKind::System, format!("failed to list agents: {err}"));
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}
