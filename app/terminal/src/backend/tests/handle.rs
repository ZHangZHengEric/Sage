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
        agent_id: None,
        agent_config: None,
        agent_mode: Some("simple".to_string()),
        max_loop_count: Some(3),
        workspace: Some(temp_dir.clone()),
        sandbox_type: None,
        sandbox_approval_mode: "on-request".to_string(),
        skills: Vec::new(),
        model_override: None,
        goal_objective: None,
        goal_status: None,
        clear_goal: false,
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

#[test]
fn backend_handle_omits_workspace_flag_when_not_overridden() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-no-workspace");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let args_path = temp_dir.join("backend-args.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());

    let request = BackendRequest {
        session_id: "local-0002".to_string(),
        user_id: "terminal-test".to_string(),
        agent_id: None,
        agent_config: None,
        agent_mode: Some("simple".to_string()),
        max_loop_count: Some(3),
        workspace: None,
        sandbox_type: None,
        sandbox_approval_mode: "on-request".to_string(),
        skills: Vec::new(),
        model_override: None,
        goal_objective: None,
        goal_status: None,
        clear_goal: false,
        task: "unused".to_string(),
    };

    let handle = BackendHandle::spawn(&request).expect("backend should spawn");
    handle
        .send_prompt("first prompt")
        .expect("prompt should be written");
    let _ = collect_round_trip(&handle);

    let args = fs::read_to_string(&args_path).expect("backend args log should exist");
    assert!(!args.lines().any(|line| line == "--workspace"));

    handle.stop();
    let _ = wait_for_exit(&handle);
}

#[test]
fn backend_handle_forwards_agent_config_flag_without_agent_id() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-agent-config");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let args_path = temp_dir.join("backend-args.log");
    let env_path = temp_dir.join("backend-env.log");
    let config_path = temp_dir.join("coding_config.json");
    fs::write(&config_path, "{}").expect("config file should be created");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());
    let _env_guard = EnvVarGuard::set("TEST_BACKEND_ENV_LOG", &env_path.display().to_string());

    let request = BackendRequest {
        session_id: "local-0003".to_string(),
        user_id: "terminal-test".to_string(),
        agent_id: Some("agent_demo".to_string()),
        agent_config: Some(config_path.clone()),
        agent_mode: None,
        max_loop_count: None,
        workspace: None,
        sandbox_type: Some("local".to_string()),
        sandbox_approval_mode: "untrusted".to_string(),
        skills: Vec::new(),
        model_override: None,
        goal_objective: None,
        goal_status: None,
        clear_goal: false,
        task: "unused".to_string(),
    };

    let handle = BackendHandle::spawn(&request).expect("backend should spawn");
    handle
        .send_prompt("first prompt")
        .expect("prompt should be written");
    let _ = collect_round_trip(&handle);

    let args = fs::read_to_string(&args_path).expect("backend args log should exist");
    let lines = args.lines().collect::<Vec<_>>();
    assert!(lines.windows(2).any(|pair| {
        pair[0] == "--agent-config" && pair[1] == config_path.display().to_string()
    }));
    assert!(!lines.iter().any(|line| *line == "--agent-id"));
    assert!(!lines.iter().any(|line| *line == "--agent-mode"));
    assert!(!lines.iter().any(|line| *line == "--max-loop-count"));
    assert!(lines
        .windows(2)
        .any(|pair| pair[0] == "--sandbox-type" && pair[1] == "local"));
    let env = fs::read_to_string(&env_path).expect("backend env log should exist");
    assert!(env.contains("SAGE_APPROVAL_MODE=untrusted"));
    assert!(env.contains("SAGE_SANDBOX_MODE=local"));

    handle.stop();
    let _ = wait_for_exit(&handle);
}
