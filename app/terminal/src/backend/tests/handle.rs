use std::fs;

use super::{
    collect_round_trip, lock_env, unique_temp_dir, wait_for_exit, write_fake_backend_script,
    EnvVarGuard,
};
use crate::backend::{BackendHandle, BackendRequest};

#[test]
fn backend_handle_supports_two_round_trips_without_respawn() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-smoke");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let log_path = temp_dir.join("backend-prompts.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());

    let request = BackendRequest {
        session_id: "local-0001".to_string(),
        user_id: "terminal-test".to_string(),
        agent_mode: "simple".to_string(),
        max_loop_count: 3,
        workspace: Some(temp_dir.clone()),
        skills: Vec::new(),
        model_override: None,
        task: "unused".to_string(),
    };

    let handle = BackendHandle::spawn(&request).expect("backend should spawn");

    handle
        .send_prompt("first prompt")
        .expect("first prompt should be written");
    let first_round = collect_round_trip(&handle);
    assert_eq!(first_round, vec!["round 1: first prompt".to_string()]);

    handle
        .send_prompt("second prompt")
        .expect("second prompt should be written");
    let second_round = collect_round_trip(&handle);
    assert_eq!(second_round, vec!["round 2: second prompt".to_string()]);

    let prompts = fs::read_to_string(&log_path).expect("backend log should exist");
    assert_eq!(
        prompts.lines().collect::<Vec<_>>(),
        vec!["first prompt", "second prompt"]
    );

    handle.stop();
    let _ = wait_for_exit(&handle);
}
