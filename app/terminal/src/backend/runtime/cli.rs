use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Result};
use serde_json::Value;

use super::{prepare_state_root, resolve_runtime_root};

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
    super::apply_state_env(&mut command, &state_root);

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
