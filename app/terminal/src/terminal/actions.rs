#[path = "actions/agents.rs"]
mod agents;
#[path = "actions/chat.rs"]
mod chat;
#[path = "actions/model.rs"]
mod model;
#[path = "actions/providers.rs"]
mod providers;
#[path = "actions/sessions.rs"]
mod sessions;
#[path = "actions/skills.rs"]
mod skills;

use anyhow::Result;

use crate::app::{App, SubmitAction};
use crate::backend::BackendHandle;

pub(super) fn handle_submit_action(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    action: SubmitAction,
) -> Result<bool> {
    match action {
        SubmitAction::Noop => Ok(false),
        SubmitAction::Handled => Ok(true),
        SubmitAction::RunTask(task) => chat::run_task(app, backend, task),
        SubmitAction::Interrupt => chat::interrupt_task(app, backend),
        SubmitAction::RetryLastTask => chat::retry_last_task(app, backend),
        SubmitAction::OpenSessionPicker { mode, limit } => {
            sessions::open_session_picker(app, mode, limit)
        }
        SubmitAction::ListAgents => agents::list_agents(app),
        SubmitAction::ListSkills => skills::list_skills(app),
        SubmitAction::EnableSkill(skill) => skills::enable_skill(app, skill),
        SubmitAction::DisableSkill(skill) => skills::disable_skill(app, &skill),
        SubmitAction::ClearSkills => skills::clear_skills(app),
        SubmitAction::ShowDoctor { probe_provider } => model::show_doctor(app, probe_provider),
        SubmitAction::ShowConfig => model::show_config(app),
        SubmitAction::InitConfig { path, force } => model::init_config(app, path.as_deref(), force),
        SubmitAction::ListProviders => providers::list_providers(app),
        SubmitAction::ShowProvider(provider_id) => providers::show_provider(app, &provider_id),
        SubmitAction::VerifyProvider(fields) => providers::verify_provider(app, &fields),
        SubmitAction::SetDefaultProvider(provider_id) => {
            providers::set_default_provider(app, backend, &provider_id)
        }
        SubmitAction::CreateProvider(fields) => providers::create_provider(app, backend, &fields),
        SubmitAction::UpdateProvider {
            provider_id,
            fields,
        } => providers::update_provider(app, backend, &provider_id, &fields),
        SubmitAction::DeleteProvider(provider_id) => {
            providers::delete_provider(app, backend, &provider_id)
        }
        SubmitAction::ShowModel => model::show_model(app),
        SubmitAction::SetModel(model) => model::set_model(app, model),
        SubmitAction::ClearModel => model::clear_model(app),
        SubmitAction::ResumeLatest => sessions::resume_latest(app),
        SubmitAction::ResumeSession(session_id) => sessions::resume_session(app, &session_id),
        SubmitAction::ShowSession(session_id) => sessions::show_session(app, &session_id),
    }
}
