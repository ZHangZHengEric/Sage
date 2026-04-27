use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Result};
use serde_json::Value;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum CliInvoker {
    Executable(PathBuf),
    PythonModule(PathBuf),
}

impl CliInvoker {
    pub(crate) fn display(&self) -> String {
        match self {
            Self::Executable(path) | Self::PythonModule(path) => path.display().to_string(),
        }
    }
}

pub(crate) fn repo_root() -> Result<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .and_then(|path| path.parent())
        .map(PathBuf::from)
        .ok_or_else(|| anyhow!("failed to resolve repo root from CARGO_MANIFEST_DIR"))
}

pub(crate) fn resolve_runtime_root() -> Result<PathBuf> {
    resolve_runtime_root_from(std::env::current_exe().ok())
}

pub(crate) fn resolve_runtime_root_from(current_exe: Option<PathBuf>) -> Result<PathBuf> {
    if let Ok(explicit_root) = std::env::var("SAGE_TERMINAL_RUNTIME_ROOT") {
        let path = PathBuf::from(explicit_root);
        if is_runtime_root(&path) {
            return Ok(path);
        }
        return Err(anyhow!(
            "SAGE_TERMINAL_RUNTIME_ROOT does not contain app/cli/main.py: {}",
            path.display()
        ));
    }

    for candidate in runtime_root_candidates(current_exe) {
        if is_runtime_root(&candidate) {
            return Ok(candidate);
        }
    }

    Err(anyhow!(
        "failed to resolve Sage runtime root; set SAGE_TERMINAL_RUNTIME_ROOT or run from a Sage checkout"
    ))
}

pub(crate) fn resolve_python_command(runtime_root: &Path) -> PathBuf {
    if let Ok(python) = std::env::var("SAGE_PYTHON") {
        return PathBuf::from(python);
    }
    if let Ok(python) = std::env::var("PYTHON") {
        return PathBuf::from(python);
    }

    bundled_python_candidates(runtime_root)
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from("python3"))
}

pub(crate) fn resolve_cli_invoker(runtime_root: &Path) -> CliInvoker {
    if let Ok(cli) = std::env::var("SAGE_TERMINAL_CLI") {
        return CliInvoker::Executable(PathBuf::from(cli));
    }

    if let Some(cli) = bundled_cli_candidates(runtime_root)
        .into_iter()
        .find(|path| path.is_file())
    {
        return CliInvoker::Executable(cli);
    }

    CliInvoker::PythonModule(resolve_python_command(runtime_root))
}

pub(crate) fn run_cli_json(args: &[&str]) -> Result<Value> {
    let runtime_root = resolve_runtime_root()?;
    let state_root = prepare_state_root(&runtime_root)?;
    let cli = resolve_cli_invoker(&runtime_root);

    let mut command = match &cli {
        CliInvoker::Executable(path) => {
            let mut command = Command::new(path);
            command.current_dir(&runtime_root);
            command
        }
        CliInvoker::PythonModule(path) => {
            let mut command = Command::new(path);
            command
                .current_dir(&runtime_root)
                .arg("-m")
                .arg("app.cli.main");
            command
        }
    };
    for arg in args {
        command.arg(arg);
    }
    apply_state_env(&mut command, &state_root);

    let output = command.output().map_err(|err| {
        anyhow!(
            "failed to launch Sage CLI helper with {}: {err}",
            cli.display()
        )
    })?;

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

fn is_runtime_root(path: &Path) -> bool {
    path.join("app").join("cli").join("main.py").is_file()
}

fn runtime_root_candidates(current_exe: Option<PathBuf>) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(exe) = current_exe {
        if let Some(bin_dir) = exe.parent() {
            candidates.push(bin_dir.to_path_buf());
            if let Some(parent) = bin_dir.parent() {
                candidates.push(parent.to_path_buf());
                candidates.push(parent.join("runtime"));
                candidates.push(parent.join("share").join("sage"));
                candidates.push(parent.join("Resources").join("sage"));
                candidates.push(parent.join("resources").join("sage"));
            }
        }
    }
    if let Ok(repo_root) = repo_root() {
        candidates.push(repo_root);
    }
    dedupe_paths(candidates)
}

fn bundled_python_candidates(runtime_root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    for relative in [
        [".venv", "bin", "python3"].as_slice(),
        [".venv", "bin", "python"].as_slice(),
        ["bin", "python3"].as_slice(),
        ["bin", "python"].as_slice(),
        ["python", "bin", "python3"].as_slice(),
        ["python", "bin", "python"].as_slice(),
        [".sage_py_env", "bin", "python3"].as_slice(),
        [".sage_py_env", "bin", "python"].as_slice(),
    ] {
        let mut path = runtime_root.to_path_buf();
        for segment in relative {
            path.push(segment);
        }
        candidates.push(path);
    }

    #[cfg(target_os = "windows")]
    {
        for relative in [
            [".venv", "Scripts", "python.exe"].as_slice(),
            ["python", "python.exe"].as_slice(),
            [".sage_py_env", "Scripts", "python.exe"].as_slice(),
        ] {
            let mut path = runtime_root.to_path_buf();
            for segment in relative {
                path.push(segment);
            }
            candidates.push(path);
        }
    }

    candidates
}

fn bundled_cli_candidates(runtime_root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    for relative in [
        [".venv", "bin", "sage"].as_slice(),
        ["bin", "sage"].as_slice(),
        ["python", "bin", "sage"].as_slice(),
        [".sage_py_env", "bin", "sage"].as_slice(),
    ] {
        let mut path = runtime_root.to_path_buf();
        for segment in relative {
            path.push(segment);
        }
        candidates.push(path);
    }

    #[cfg(target_os = "windows")]
    {
        for relative in [
            [".venv", "Scripts", "sage.exe"].as_slice(),
            ["Scripts", "sage.exe"].as_slice(),
            ["python", "Scripts", "sage.exe"].as_slice(),
            [".sage_py_env", "Scripts", "sage.exe"].as_slice(),
        ] {
            let mut path = runtime_root.to_path_buf();
            for segment in relative {
                path.push(segment);
            }
            candidates.push(path);
        }
    }

    candidates
}

fn dedupe_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for path in paths {
        if !out.iter().any(|existing| existing == &path) {
            out.push(path);
        }
    }
    out
}
