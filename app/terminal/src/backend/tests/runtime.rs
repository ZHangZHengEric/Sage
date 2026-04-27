use std::fs;
use std::path::PathBuf;
use std::process::Command;

use super::{lock_env, unique_temp_dir, EnvVarGuard};
use crate::backend::runtime::{
    apply_state_env, prepare_state_root, resolve_cli_invoker, resolve_python_command,
    resolve_runtime_root_from, CliInvoker,
};

#[test]
fn prepare_state_root_copies_builtin_skills_into_terminal_workspace() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("builtin-skills");
    let builtin_skill = temp_dir.join("app").join("skills").join("demo-skill");
    fs::create_dir_all(builtin_skill.join("references"))
        .expect("builtin skill directory should be created");
    fs::write(
        builtin_skill.join("SKILL.md"),
        "---\nname: demo-skill\ndescription: demo\n---\n",
    )
    .expect("skill manifest should be written");
    fs::write(
        builtin_skill.join("references").join("guide.md"),
        "demo reference",
    )
    .expect("skill reference should be written");
    let state_root = temp_dir.join("terminal-state");
    let _state_root_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_STATE_ROOT",
        &state_root.display().to_string(),
    );

    let state_root = prepare_state_root(&temp_dir).expect("state root should be prepared");
    let copied_skill = state_root.join("skills").join("demo-skill");
    assert!(copied_skill.join("SKILL.md").is_file());
    assert_eq!(
        fs::read_to_string(copied_skill.join("references").join("guide.md"))
            .expect("copied reference should exist"),
        "demo reference"
    );
}

#[test]
fn prepare_state_root_uses_home_for_packaged_runtime_layout() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("packaged-runtime");
    fs::create_dir_all(runtime_root.join("app").join("skills")).expect("runtime root should exist");
    let home_dir = unique_temp_dir("terminal-home");
    fs::create_dir_all(&home_dir).expect("home dir should exist");
    let _home_guard = EnvVarGuard::set("HOME", &home_dir.display().to_string());

    let state_root = prepare_state_root(&runtime_root).expect("state root should be prepared");

    assert_eq!(state_root, home_dir.join(".sage").join("terminal-state"));
    assert!(state_root.join("logs").is_dir());
}

#[test]
fn apply_state_env_keeps_default_sage_session_dir() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("state-env");
    let state_root_path = temp_dir.join("terminal-state");
    let _state_root_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_STATE_ROOT",
        &state_root_path.display().to_string(),
    );
    let state_root = prepare_state_root(&temp_dir).expect("state root should be prepared");
    let mut command = Command::new("true");

    apply_state_env(&mut command, &state_root);

    let envs = command
        .get_envs()
        .map(|(key, value)| {
            (
                key.to_string_lossy().to_string(),
                value.map(|value| value.to_string_lossy().to_string()),
            )
        })
        .collect::<Vec<_>>();

    assert!(!envs.iter().any(|(key, _)| key == "SAGE_SESSION_DIR"));
    assert!(envs.iter().any(|(key, value)| {
        key == "SAGE_LOGS_DIR_PATH"
            && value
                .as_deref()
                .is_some_and(|value| value.ends_with("terminal-state/logs"))
    }));
}

#[test]
fn resolve_runtime_root_prefers_explicit_env_override() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("runtime-root");
    fs::create_dir_all(runtime_root.join("app").join("cli")).expect("runtime cli dir should exist");
    fs::write(
        runtime_root.join("app").join("cli").join("main.py"),
        "# stub",
    )
    .expect("runtime entry should exist");
    let _runtime_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_RUNTIME_ROOT",
        &runtime_root.display().to_string(),
    );

    let resolved = resolve_runtime_root_from(None).expect("runtime root should resolve");
    assert_eq!(resolved, runtime_root);
}

#[test]
fn resolve_python_command_prefers_bundled_runtime_python() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-python");
    let python_path = runtime_root.join(".venv").join("bin").join("python3");
    fs::create_dir_all(python_path.parent().expect("parent should exist"))
        .expect("python dir should exist");
    fs::write(&python_path, "").expect("python stub should be written");
    let _sage_python_guard = EnvVarGuard::unset("SAGE_PYTHON");
    let _python_guard = EnvVarGuard::unset("PYTHON");

    let resolved = resolve_python_command(&runtime_root);
    assert_eq!(resolved, python_path);
}

#[test]
fn resolve_cli_invoker_prefers_explicit_env_override() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-cli-env");
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", "sage");
    let _python_guard = EnvVarGuard::set("SAGE_PYTHON", "/tmp/should-not-be-used");

    let resolved = resolve_cli_invoker(&runtime_root);
    assert_eq!(resolved, CliInvoker::Executable(PathBuf::from("sage")));
}

#[test]
fn resolve_cli_invoker_prefers_bundled_sage_over_python_module() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-cli");
    let sage_path = runtime_root.join(".venv").join("bin").join("sage");
    fs::create_dir_all(sage_path.parent().expect("parent should exist"))
        .expect("sage dir should exist");
    fs::write(&sage_path, "").expect("sage stub should be written");
    let _cli_guard = EnvVarGuard::unset("SAGE_TERMINAL_CLI");
    let _python_guard = EnvVarGuard::set("SAGE_PYTHON", "/tmp/python-fallback");

    let resolved = resolve_cli_invoker(&runtime_root);
    assert_eq!(resolved, CliInvoker::Executable(sage_path));
}
