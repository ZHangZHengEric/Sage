use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Result};
use serde_json::Value;

pub(crate) fn repo_root() -> Result<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .and_then(|path| path.parent())
        .map(PathBuf::from)
        .ok_or_else(|| anyhow!("failed to resolve repo root from CARGO_MANIFEST_DIR"))
}

pub(crate) fn run_cli_json(args: &[&str]) -> Result<Value> {
    let repo_root = repo_root()?;
    let state_root = prepare_state_root(&repo_root)?;
    let python = std::env::var("PYTHON").unwrap_or_else(|_| "python3".to_string());

    let mut command = Command::new(&python);
    command
        .current_dir(&repo_root)
        .arg("-m")
        .arg("app.cli.main");
    for arg in args {
        command.arg(arg);
    }
    apply_state_env(&mut command, &state_root);

    let output = command
        .output()
        .map_err(|err| anyhow!("failed to launch Sage CLI helper with {python}: {err}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let detail = if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            format!("exit {}", output.status)
        };
        return Err(anyhow!("Sage CLI helper failed: {detail}"));
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let json_start = stdout
        .find(['{', '['])
        .ok_or_else(|| anyhow!("invalid Sage CLI JSON: missing JSON payload"))?;
    let payload = &stdout[json_start..];
    serde_json::from_str::<Value>(payload).map_err(|err| anyhow!("invalid Sage CLI JSON: {err}"))
}

pub(crate) fn run_cli_json_owned(args: &[String]) -> Result<Value> {
    let refs = args.iter().map(String::as_str).collect::<Vec<_>>();
    run_cli_json(&refs)
}

pub(crate) fn prepare_state_root(repo_root: &Path) -> Result<PathBuf> {
    let state_root = repo_root.join(".sage-terminal-state");
    for dir in [
        state_root.join("logs"),
        state_root.join("sessions"),
        state_root.join("agents"),
        state_root.join("users"),
        state_root.join("skills"),
    ] {
        ensure_dir(&dir)?;
    }
    sync_builtin_skills(repo_root, &state_root.join("skills"))?;
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

fn sync_builtin_skills(repo_root: &Path, target_root: &Path) -> Result<()> {
    let builtin_root = repo_root.join("app").join("skills");
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
