mod formatting;
mod interaction;
mod provider_args;

#[test]
fn startup_task_initializes_run_state_without_restarting_its_backend() {
    use crate::app::{App, SubmitAction};
    use crate::backend::BackendRuntime;

    for runtime in [BackendRuntime::V1, BackendRuntime::V2] {
        let mut app = App::new();
        app.set_runtime_selection(runtime);
        let action = SubmitAction::RunTask("execute startup task".to_string());
        super::prepare_startup_action(&mut app, Some(&action));
        assert!(app.busy);
        assert_eq!(app.current_task.as_deref(), Some("execute startup task"));
        assert_ne!(app.session_label(), "new");
        assert!(!app.take_backend_restart_request());
    }
}
