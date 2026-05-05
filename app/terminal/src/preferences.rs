use std::fs;
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};

use crate::app::{normalize_agent_mode, App, MessageKind};
use crate::backend::runtime::{prepare_state_root, resolve_runtime_root};
use crate::display_policy::DisplayMode;
use crate::startup::StartupOptions;

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
struct TerminalPreferences {
    agent_id: Option<String>,
    agent_mode: Option<String>,
    display_mode: Option<DisplayMode>,
    workspace: Option<String>,
}

pub(crate) fn load_startup_preferences() -> Result<StartupOptions> {
    let path = preferences_path()?;
    if !path.is_file() {
        return Ok(StartupOptions::default());
    }

    let raw = fs::read_to_string(&path)
        .map_err(|err| anyhow!("failed to read {}: {err}", path.display()))?;
    let preferences = serde_json::from_str::<TerminalPreferences>(&raw)
        .map_err(|err| anyhow!("failed to parse {}: {err}", path.display()))?;
    Ok(StartupOptions {
        agent_id: preferences
            .agent_id
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty()),
        agent_mode: preferences
            .agent_mode
            .as_deref()
            .and_then(normalize_agent_mode),
        display_mode: preferences.display_mode,
        workspace: preferences
            .workspace
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty()),
    })
}

pub(crate) fn persist_app_preferences_notice(app: &mut App) {
    if should_skip_test_persistence() {
        return;
    }
    if let Err(err) = save_app_preferences(app) {
        app.push_message(
            MessageKind::System,
            format!("failed to save terminal preferences: {err}"),
        );
    }
}

fn save_app_preferences(app: &App) -> Result<()> {
    let path = preferences_path()?;
    let preferences = TerminalPreferences {
        agent_id: app.selected_agent_id.clone(),
        agent_mode: Some(app.agent_mode.clone()),
        display_mode: Some(app.display_mode),
        workspace: app
            .workspace_override_path()
            .map(|path| path.display().to_string()),
    };
    let payload = serde_json::to_string_pretty(&preferences)
        .map_err(|err| anyhow!("failed to encode terminal preferences: {err}"))?;
    fs::write(&path, payload).map_err(|err| anyhow!("failed to write {}: {err}", path.display()))
}

fn preferences_path() -> Result<PathBuf> {
    let runtime_root = resolve_runtime_root()?;
    let state_root = prepare_state_root(&runtime_root)?;
    Ok(state_root.join("terminal-preferences.json"))
}

fn should_skip_test_persistence() -> bool {
    cfg!(test)
        && std::env::var("SAGE_TERMINAL_STATE_ROOT").is_err()
        && std::env::var("SAGE_TERMINAL_RUNTIME_ROOT").is_err()
}

#[cfg(test)]
mod tests {
    use std::env;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::{Mutex, MutexGuard, OnceLock};
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::{load_startup_preferences, persist_app_preferences_notice};
    use crate::app::App;
    use crate::display_policy::DisplayMode;

    #[test]
    fn persisted_preferences_load_back_into_startup_options() {
        let _env_lock = lock_env();
        let runtime_root = unique_temp_dir("preferences-runtime");
        fs::create_dir_all(runtime_root.join("app").join("cli"))
            .expect("runtime cli dir should exist");
        fs::write(
            runtime_root.join("app").join("cli").join("main.py"),
            "# stub",
        )
        .expect("runtime entry should exist");
        let state_root = unique_temp_dir("preferences-state");
        let _runtime_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_RUNTIME_ROOT",
            &runtime_root.display().to_string(),
        );
        let _state_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_STATE_ROOT",
            &state_root.display().to_string(),
        );

        let mut app = App::new();
        app.set_display_mode(DisplayMode::Verbose);
        app.set_selected_agent_id("agent_demo".to_string());
        app.set_agent_mode_selection("multi".to_string());
        app.set_workspace_selection("/tmp/demo-workspace".to_string());
        let loaded = load_startup_preferences().expect("preferences should load");

        assert_eq!(loaded.agent_id.as_deref(), Some("agent_demo"));
        assert_eq!(loaded.agent_mode.as_deref(), Some("multi"));
        assert_eq!(loaded.display_mode, Some(DisplayMode::Verbose));
        assert_eq!(loaded.workspace.as_deref(), Some("/tmp/demo-workspace"));
    }

    #[test]
    fn persisted_preferences_restore_into_new_app_state() {
        let _env_lock = lock_env();
        let runtime_root = unique_temp_dir("preferences-restore-runtime");
        fs::create_dir_all(runtime_root.join("app").join("cli"))
            .expect("runtime cli dir should exist");
        fs::write(
            runtime_root.join("app").join("cli").join("main.py"),
            "# stub",
        )
        .expect("runtime entry should exist");
        let state_root = unique_temp_dir("preferences-restore-state");
        let _runtime_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_RUNTIME_ROOT",
            &runtime_root.display().to_string(),
        );
        let _state_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_STATE_ROOT",
            &state_root.display().to_string(),
        );

        let mut original = App::new();
        original.set_display_mode(DisplayMode::Verbose);
        original.set_selected_agent_id("agent_demo".to_string());
        original.set_agent_mode_selection("multi".to_string());
        original.set_workspace_selection("/tmp/demo-workspace".to_string());

        let options = crate::startup::StartupOptions::default()
            .with_fallbacks(load_startup_preferences().expect("preferences should load"));
        let mut restored = App::new();
        restored.apply_startup_options(
            options.agent_id,
            options.agent_mode,
            options.display_mode,
            options.workspace.map(PathBuf::from),
        );

        assert_eq!(restored.selected_agent_id.as_deref(), Some("agent_demo"));
        assert_eq!(restored.agent_mode, "multi");
        assert_eq!(restored.display_mode, DisplayMode::Verbose);
        assert_eq!(restored.workspace_label, "/tmp/demo-workspace");
    }

    #[test]
    fn clearing_preferences_updates_saved_defaults() {
        let _env_lock = lock_env();
        let runtime_root = unique_temp_dir("preferences-clear-runtime");
        fs::create_dir_all(runtime_root.join("app").join("cli"))
            .expect("runtime cli dir should exist");
        fs::write(
            runtime_root.join("app").join("cli").join("main.py"),
            "# stub",
        )
        .expect("runtime entry should exist");
        let state_root = unique_temp_dir("preferences-clear-state");
        let _runtime_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_RUNTIME_ROOT",
            &runtime_root.display().to_string(),
        );
        let _state_guard = EnvVarGuard::set(
            "SAGE_TERMINAL_STATE_ROOT",
            &state_root.display().to_string(),
        );

        let mut app = App::new();
        app.set_selected_agent_id("agent_demo".to_string());
        app.set_workspace_selection("/tmp/demo-workspace".to_string());
        app.clear_selected_agent_id();
        app.clear_workspace_override_selection();
        persist_app_preferences_notice(&mut app);

        let loaded = load_startup_preferences().expect("preferences should load");
        assert!(loaded.agent_id.is_none());
        assert!(loaded.workspace.is_none());
    }

    fn lock_env() -> MutexGuard<'static, ()> {
        static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        ENV_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    struct EnvVarGuard {
        key: &'static str,
        previous: Option<String>,
    }

    impl EnvVarGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let previous = env::var(key).ok();
            unsafe {
                env::set_var(key, value);
            }
            Self { key, previous }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => unsafe {
                    env::set_var(self.key, value);
                },
                None => unsafe {
                    env::remove_var(self.key);
                },
            }
        }
    }

    fn unique_temp_dir(label: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should move forward")
            .as_nanos();
        env::temp_dir().join(format!("sage-terminal-{label}-{suffix}"))
    }
}
