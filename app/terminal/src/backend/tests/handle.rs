use std::fs;

use serde_json::Value;

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
    let args_path = temp_dir.join("backend-args.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());

    let request = BackendRequest {
        runtime: crate::backend::BackendRuntime::V1,
        resume_session: false,
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
    let args = fs::read_to_string(&args_path).expect("backend args log should exist");
    let lines = args.lines().collect::<Vec<_>>();
    assert!(lines
        .windows(2)
        .any(|pair| { pair[0] == "--workspace" && pair[1] == temp_dir.display().to_string() }));

    handle.stop();
    let _ = wait_for_exit(&handle);
}

#[test]
fn backend_handle_writes_sandbox_approval_decision_to_stdin() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-approval-decision");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let log_path = temp_dir.join("backend-prompts.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());

    let request = BackendRequest {
        runtime: crate::backend::BackendRuntime::V1,
        resume_session: false,
        session_id: "local-approval".to_string(),
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
        .send_sandbox_approval_decision(
            "local-approval",
            "shapproval_demo",
            Some("hash_demo"),
            "approve",
        )
        .expect("approval decision should be written");
    let _ = collect_round_trip(&handle);

    let prompts = fs::read_to_string(&log_path).expect("backend log should exist");
    let payload: Value =
        serde_json::from_str(prompts.lines().next().expect("decision line should exist"))
            .expect("decision should be JSON");
    assert_eq!(payload["type"], "sandbox_approval_decision");
    assert_eq!(payload["session_id"], "local-approval");
    assert_eq!(payload["approval_id"], "shapproval_demo");
    assert_eq!(payload["command_hash"], "hash_demo");
    assert_eq!(payload["decision"], "approve");

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
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", &script_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());

    let request = BackendRequest {
        runtime: crate::backend::BackendRuntime::V1,
        resume_session: false,
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
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", &script_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());
    let _env_guard = EnvVarGuard::set("TEST_BACKEND_ENV_LOG", &env_path.display().to_string());

    let request = BackendRequest {
        runtime: crate::backend::BackendRuntime::V1,
        resume_session: false,
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
    assert!(lines
        .windows(2)
        .any(|pair| pair[0] == "--sandbox-approval-mode" && pair[1] == "untrusted"));
    let env = fs::read_to_string(&env_path).expect("backend env log should exist");
    assert!(env.contains("SAGE_APPROVAL_MODE=untrusted"));
    assert!(env.contains("SAGE_SANDBOX_MODE=local"));

    handle.stop();
    let _ = wait_for_exit(&handle);
}

#[test]
fn backend_handle_spawns_v2_chat_and_writes_v2_decision_frames() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-v2");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let log_path = temp_dir.join("backend-prompts.log");
    let args_path = temp_dir.join("backend-args.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());
    let _args_guard = EnvVarGuard::set("TEST_BACKEND_ARGS_LOG", &args_path.display().to_string());

    let request = BackendRequest {
        runtime: crate::backend::BackendRuntime::V2,
        resume_session: false,
        session_id: "new".to_string(),
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

    let handle = BackendHandle::spawn(&request).expect("v2 backend should spawn");
    assert_eq!(handle.runtime(), crate::backend::BackendRuntime::V2);
    handle
        .send_prompt("first prompt")
        .expect("prompt should be written");
    let _ = collect_round_trip(&handle);

    // v1 语义的 approve/deny 映射成 v2 决策帧；remember 只有 v2 才有。
    handle
        .send_sandbox_approval_decision("new", "interaction_1", None, "approve")
        .expect("approve should be written");
    handle
        .send_sandbox_approval_decision("new", "interaction_1", None, "remember")
        .expect("remember should be written");
    handle
        .send_v2_interaction_decision(
            "interaction_2",
            "submit",
            serde_json::json!({"text": "staging"}),
        )
        .expect("answer should be written");
    // 让假后端把三行决策都吃掉（每行触发一轮输出）。
    for _ in 0..3 {
        let _ = collect_round_trip(&handle);
    }

    let args = fs::read_to_string(&args_path).expect("backend args log should exist");
    let lines = args.lines().collect::<Vec<_>>();
    assert_eq!(&lines[..3], &["v2", "chat", "--json"]);
    assert!(lines
        .windows(2)
        .any(|pair| pair == ["--user-id", "terminal-test"]));
    assert!(lines
        .windows(2)
        .any(|pair| pair[0] == "--workspace" && pair[1] == temp_dir.display().to_string()));
    assert!(
        !lines.contains(&"--session-id"),
        "new v2 sessions must not pass a TUI-made id"
    );
    assert!(!lines.contains(&"--stats"));

    let prompts = fs::read_to_string(&log_path).expect("backend log should exist");
    let mut prompt_lines = prompts.lines();
    assert_eq!(prompt_lines.next(), Some("first prompt"));
    let approve: Value = serde_json::from_str(prompt_lines.next().expect("approve line")).unwrap();
    assert_eq!(approve["type"], "v2_interaction_decision");
    assert_eq!(approve["interaction_id"], "interaction_1");
    assert_eq!(approve["decision"], "approve_once");
    let remember: Value =
        serde_json::from_str(prompt_lines.next().expect("remember line")).unwrap();
    assert_eq!(remember["decision"], "approve_and_remember");
    let answer: Value = serde_json::from_str(prompt_lines.next().expect("answer line")).unwrap();
    assert_eq!(answer["interaction_id"], "interaction_2");
    assert_eq!(answer["decision"], "submit");
    assert_eq!(answer["payload"]["text"], "staging");

    handle.stop();
    let _ = wait_for_exit(&handle);

    // 已知会话（拿到过 cli_v2_session）才回传 --session-id；切换运行时会触发重启。
    let resume = BackendRequest {
        resume_session: true,
        session_id: "session_known".to_string(),
        ..request
    };
    assert!(!handle.matches(&resume));
    let _ = fs::remove_file(&args_path);
    let resumed = BackendHandle::spawn(&resume).expect("v2 backend should spawn");
    resumed
        .send_prompt("again")
        .expect("prompt should be written");
    let _ = collect_round_trip(&resumed);
    let args = fs::read_to_string(&args_path).expect("backend args log should exist");
    assert!(args
        .lines()
        .collect::<Vec<_>>()
        .windows(2)
        .any(|pair| pair == ["--session-id", "session_known"]));
    resumed.stop();
    let _ = wait_for_exit(&resumed);
}
