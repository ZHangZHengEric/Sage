use std::path::{Path, PathBuf};

use anyhow::{anyhow, Result};

use crate::backend::runtime::state::is_runtime_root;

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

fn dedupe_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for path in paths {
        if !out.iter().any(|existing| existing == &path) {
            out.push(path);
        }
    }
    out
}

#[allow(dead_code)]
fn _assert_path_send_sync(_: &Path) {}
