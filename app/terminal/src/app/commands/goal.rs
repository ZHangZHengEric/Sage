use crate::app::{App, MessageKind, PendingGoalMutation};

impl App {
    pub fn set_goal_selection(&mut self, objective: String) {
        let normalized = objective.trim().to_string();
        if normalized.is_empty() {
            self.queue_message(MessageKind::System, "goal objective cannot be empty");
            self.status = format!("goal  {}", self.session_id);
            return;
        }

        self.current_goal = Some(crate::backend::BackendGoal {
            objective: normalized.clone(),
            status: "active".to_string(),
        });
        self.pending_goal_mutation = Some(PendingGoalMutation {
            objective: Some(normalized.clone()),
            status: Some("active".to_string()),
            clear: false,
        });
        self.queue_message(MessageKind::Tool, format!("goal set: {normalized}"));
        self.status = format!("goal  {}", self.session_id);
    }

    pub fn clear_goal_selection(&mut self) {
        self.current_goal = None;
        self.pending_goal_mutation = Some(PendingGoalMutation {
            objective: None,
            status: None,
            clear: true,
        });
        self.queue_message(MessageKind::Tool, "goal clear queued");
        self.status = format!("goal  {}", self.session_id);
    }

    pub fn complete_goal_selection(&mut self) {
        if self
            .pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.objective.as_ref())
            .is_some()
        {
            self.queue_message(
                MessageKind::System,
                "goal is queued and will exist after the next request",
            );
            self.status = format!("goal  {}", self.session_id);
            return;
        }

        let Some(goal) = self.current_goal.as_mut() else {
            self.queue_message(MessageKind::System, "no active goal");
            self.status = format!("goal  {}", self.session_id);
            return;
        };

        goal.status = "completed".to_string();
        let objective = goal.objective.clone();
        self.pending_goal_mutation = Some(PendingGoalMutation {
            objective: None,
            status: Some("completed".to_string()),
            clear: false,
        });
        self.queue_message(
            MessageKind::Tool,
            format!("goal marked complete: {objective}"),
        );
        self.status = format!("goal  {}", self.session_id);
    }

    pub fn queue_goal_status(&mut self) {
        let goal_text = match (&self.current_goal, &self.pending_goal_mutation) {
            (_, Some(pending)) if pending.clear => {
                "goal: (clearing on next request)\ngoal_pending: clear".to_string()
            }
            (_, Some(pending)) if pending.objective.is_some() => format!(
                "goal: {}\ngoal_status: {}\ngoal_pending: set",
                pending.objective.clone().unwrap_or_default(),
                pending
                    .status
                    .clone()
                    .unwrap_or_else(|| "active".to_string())
            ),
            (Some(goal), Some(pending)) if pending.status.is_some() => format!(
                "goal: {}\ngoal_status: {}\ngoal_pending: {}",
                goal.objective,
                goal.status,
                pending.status.clone().unwrap_or_default()
            ),
            (Some(goal), _) => format!("goal: {}\ngoal_status: {}", goal.objective, goal.status),
            (None, _) => "goal: (none)".to_string(),
        };

        self.queue_message(MessageKind::System, goal_text);
        self.status = format!("goal  {}", self.session_id);
    }
}
