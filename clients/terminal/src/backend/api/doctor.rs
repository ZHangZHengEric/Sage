use anyhow::Result;
use serde_json::Value;

use crate::backend::contract::{run_cli_command, CliJsonCommand};

pub(crate) fn read_doctor_info(probe_provider: bool) -> Result<Value> {
    run_cli_command(CliJsonCommand::Doctor { probe_provider })
}
