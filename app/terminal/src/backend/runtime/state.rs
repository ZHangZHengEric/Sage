use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Result};

pub(crate) fn prepare_state_root(runtime_root: &Path) -> Result<PathBuf> {
    let state_root = resolve_state_root(runtime_root);
    for dir in [
        state_root.join("logs"),
        state_root.join("sessions"),
        state_root.join("agents"),
        state_root.join("users"),
        state_root.join("skills"),
    ] {
        ensure_dir(&dir)?;
    }
    sync_builtin_skills(runtime_root, &state_root.join("skills"))?;
    Ok(state_root)
}

pub(crate) fn apply_state_env(command: &mut Command, state_root: &Path) {
    command
        .env("SAGE_LOGS_DIR_PATH", state_root.join("logs"))
        .env("SAGE_AGENTS_DIR", state_root.join("agents"))
        .env("SAGE_USER_DIR", state_root.join("users"))
        .env("SAGE_DB_FILE", state_root.join("sage.db"))
        .env("SAGE_SKILL_WORKSPACE", state_root.join("skills"));
}

pub(crate) fn is_runtime_root(path: &Path) -> bool {
    path.join("app").join("cli").join("main.py").is_file()
}

fn sync_builtin_skills(runtime_root: &Path, target_root: &Path) -> Result<()> {
    let builtin_root = runtime_root.join("app").join("skills");
    if !builtin_root.is_dir() {
        return Ok(());
    }

    for entry in fs::read_dir(&builtin_root).map_err(|err| {
        anyhow!(
            "failed to read built-in skills from {}: {err}",
            builtin_root.display()
        )
    })? {
        let entry =
            entry.map_err(|err| anyhow!("failed to inspect built-in skill entry: {err}"))?;
        let source_path = entry.path();
        if !source_path.is_dir() || !source_path.join("SKILL.md").is_file() {
            continue;
        }

        let target_path = target_root.join(entry.file_name());
        if target_path.exists() {
            continue;
        }

        copy_dir_recursive(&source_path, &target_path)?;
    }

    Ok(())
}

fn copy_dir_recursive(source: &Path, target: &Path) -> Result<()> {
    ensure_dir(target)?;
    for entry in fs::read_dir(source)
        .map_err(|err| anyhow!("failed to read directory {}: {err}", source.display()))?
    {
        let entry = entry
            .map_err(|err| anyhow!("failed to inspect entry in {}: {err}", source.display()))?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        if source_path.is_dir() {
            copy_dir_recursive(&source_path, &target_path)?;
        } else {
            fs::copy(&source_path, &target_path).map_err(|err| {
                anyhow!(
                    "failed to copy {} to {}: {err}",
                    source_path.display(),
                    target_path.display()
                )
            })?;
        }
    }
    Ok(())
}

fn ensure_dir(path: &Path) -> Result<()> {
    fs::create_dir_all(path).map_err(|err| match err.kind() {
        io::ErrorKind::AlreadyExists => {
            anyhow!("path exists and is not a directory: {}", path.display())
        }
        _ => anyhow!("failed to create {}: {err}", path.display()),
    })
}

fn resolve_state_root(runtime_root: &Path) -> PathBuf {
    if let Ok(explicit_root) = std::env::var("SAGE_TERMINAL_STATE_ROOT") {
        return PathBuf::from(explicit_root);
    }
    if runtime_root.join(".git").exists() {
        return runtime_root.join(".sage-terminal-state");
    }
    if let Ok(home) = std::env::var("HOME") {
        return PathBuf::from(home).join(".sage").join("terminal-state");
    }
    runtime_root.join(".sage-terminal-state")
}
