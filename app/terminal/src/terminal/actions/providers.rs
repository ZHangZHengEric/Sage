use anyhow::Result;

use crate::app::{App, MessageKind};
use crate::backend::{
    create_provider as create_provider_api, delete_provider as delete_provider_api,
    inspect_provider, list_providers as list_providers_api,
    set_default_provider as set_default_provider_api, update_provider as update_provider_api,
    verify_provider as verify_provider_api, BackendHandle,
};
use crate::terminal::stop_backend;
use crate::terminal_support::{
    format_provider_detail, format_provider_verify, format_providers, parse_provider_mutation,
    parse_provider_mutation_allow_empty,
};

pub(super) fn list_providers(app: &mut App) -> Result<bool> {
    match list_providers_api(&app.user_id) {
        Ok(providers) => {
            app.set_provider_catalog(
                providers
                    .iter()
                    .map(|provider| {
                        (
                            provider.id.clone(),
                            provider.name.clone(),
                            provider.model.clone(),
                            provider.base_url.clone(),
                            provider.is_default,
                        )
                    })
                    .collect(),
            );
            app.push_message(MessageKind::Tool, format_providers(&providers));
            app.set_status(format!("providers  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to list providers: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn show_provider(app: &mut App, provider_id: &str) -> Result<bool> {
    match inspect_provider(&app.user_id, provider_id) {
        Ok(provider) => {
            app.push_message(MessageKind::Tool, format_provider_detail(&provider));
            app.set_status(format!("provider  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to inspect provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn set_default_provider(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    provider_id: &str,
) -> Result<bool> {
    match set_default_provider_api(&app.user_id, provider_id) {
        Ok(provider) => {
            stop_backend(backend.take());
            app.clear_provider_catalog();
            app.push_message(
                MessageKind::Tool,
                format!(
                    "default provider set\n{}",
                    format_provider_detail(&provider)
                ),
            );
            if !provider.model.is_empty() {
                app.selected_model = None;
            }
            app.set_status(format!("provider  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to update provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn verify_provider(app: &mut App, fields: &[String]) -> Result<bool> {
    match parse_provider_mutation_allow_empty(fields, false)
        .and_then(|mutation| verify_provider_api(&mutation))
    {
        Ok(result) => {
            app.push_message(MessageKind::Tool, format_provider_verify(&result));
            app.set_status(format!("provider verify  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to verify provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn create_provider(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    fields: &[String],
) -> Result<bool> {
    match parse_provider_mutation(fields, true)
        .and_then(|mutation| create_provider_api(&app.user_id, &mutation))
    {
        Ok(provider) => {
            stop_backend(backend.take());
            app.clear_provider_catalog();
            app.push_message(
                MessageKind::Tool,
                format!("provider created\n{}", format_provider_detail(&provider)),
            );
            app.set_status(format!("provider  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to create provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn update_provider_action(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    provider_id: &str,
    fields: &[String],
) -> Result<bool> {
    match parse_provider_mutation(fields, false)
        .and_then(|mutation| update_provider_api(&app.user_id, provider_id, &mutation))
    {
        Ok(provider) => {
            stop_backend(backend.take());
            app.clear_provider_catalog();
            app.push_message(
                MessageKind::Tool,
                format!("provider updated\n{}", format_provider_detail(&provider)),
            );
            app.set_status(format!("provider  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to update provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn update_provider(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    provider_id: &str,
    fields: &[String],
) -> Result<bool> {
    update_provider_action(app, backend, provider_id, fields)
}

pub(super) fn delete_provider(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    provider_id: &str,
) -> Result<bool> {
    match delete_provider_api(&app.user_id, provider_id) {
        Ok(()) => {
            stop_backend(backend.take());
            app.clear_provider_catalog();
            app.push_message(
                MessageKind::Tool,
                format!("provider deleted: {}", provider_id),
            );
            app.set_status(format!("provider  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to delete provider: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}
