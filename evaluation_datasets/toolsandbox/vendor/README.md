# ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities

This software project accompanies the research paper, [ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities](https://arxiv.org/abs/2408.04682).

Recent large language models (LLMs) advancements sparked a growing research interest in tool assisted LLMs solving real-world challenges, which calls for comprehensive evaluation of tool-use capabilities. While previous works focused on either evaluating over stateless web services (RESTful API), based on a single turn user prompt, or an off-policy dialog trajectory, _ToolSandbox_ includes stateful tool execution, implicit state dependencies between tools, a built-in user simulator supporting on-policy conversational evaluation and a dynamic evaluation strategy for intermediate and final milestones over an arbitrary trajectory. We show that open source and proprietary models have a significant performance gap, and complex tasks like State Dependency, Canonicalization and Insufficient Information defined in _ToolSandbox_ are challenging even the most capable SOTA LLMs, providing brand-new insights into tool-use LLM capabilities.

## Getting started
### Installation
1. Install your favorite Python virtual environment manager. We have used the arm64 (Apple Silicon) version of Miniforge3 with Python 3.9 by downloading and running the following script: https://github.com/conda-forge/miniforge/releases/download/4.12.0-2/Miniforge3-MacOSX-arm64.sh .

2. Create a virtual environment:
```bash
conda create -n ToolSandbox python=3.9
conda activate ToolSandbox
```

3. Install the dependencies with:
```bash
pip install '.[dev]'
```

### Execution
#### Required configuration for the different user/agent roles:

The following table shows the required environment variables to set depending on the user type:

|User Type  | CLI Option         | OPENAI_API_KEY |
| --------- | ------------------ | :------------: |
| Simulator | GPT_3_5_0125       | ✅             |
| Simulator | GPT_4_0125         | ✅             |
| Simulator | GPT_4_o_2024_05_13 | ✅             |
| Human     | Cli                |                |


The following table shows the required environment variables to set depending on the agent type:

| Agent Type            | ANTHROPIC_API_KEY | HF_TOKEN | OPENAI_API_KEY | OPENAI_BASE_URL | GOOGLE_CLOUD_PROJECT or CLOUD_ML_PROJECT_ID | GOOGLE_CLOUD_REGION or CLOUD_ML_REGION |
| --------------------- | :---------------: | :------: | :------------: | :-------------: | :-----------------------------------------: | :------------------------------------: |
| Claude_3_Haiku        | ✅                |          |                |                 |                                             |                                        |
| Claude_3_Opus         | ✅                |          |                |                 |                                             |                                        |
| Claude_3_Sonnet       | ✅                |          |                |                 |                                             |                                        |
| Cli                   |                   |          |                |                 |                                             |                                        |
| Cohere_Command_R      |                   |          |                | ✅              |                                             |                                        |
| Cohere_Command_R_Plus |                   |          |                | ✅              |                                             |                                        |
| GPT_3_5_0125          |                   |          | ✅             |                 |                                             |                                        |
| GPT_4_0125            |                   |          | ✅             |                 |                                             |                                        |
| GPT_4_o_2024_05_13    |                   |          | ✅             |                 |                                             |                                        |
| Gemini_1_0            |                   |          |                |                 | ✅                                          | ✅                                     |
| Gemini_1_5            |                   |          |                |                 | ✅                                          | ✅                                     |
| Gemini_1_5_Flash      |                   |          |                |                 | ✅                                          | ✅                                     |
| Gorilla               |                   |          |                | ✅              |                                             |                                        |
| Hermes                |                   |          |                | ✅              |                                             |                                        |
| Mistral               |                   |          |                | ✅              |                                             |                                        |

The search tools in the ToolSandbox use [RapidAPI](https://rapidapi.com/hub) so in order to run those scenarios you need to have an API key and expose it in an environment variable called `RAPID_API_KEY`. Using models from the Gemini family requires setting up google authentication, e.g. by using [application default credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc).

#### Example command for a single scenario
It is recommended to just set the environment variables for the command that is running as opposed to exporting them e.g. in your `~/.bashrc` file. This makes it less likely to accidentally use stale environment variables. Here is an example command to run a ToolSandbox scenario using GPT-4o as the user simulator and Claude 3 Haiku as the agent:
```
env ANTHROPIC_API_KEY=<YOUR_ANTHROPIC_API_KEY> OPENAI_API_KEY=<YOUR_OPENAI_API_KEY> tool_sandbox --user GPT_4_o_2024_05_13 --agent Claude_3_Haiku --scenario wifi_off
```

Artifacts will be stored under the `data` folder within the repository's root directory. You can for example take a look at `data/agent_claude-3-haiku-20240307_user_gpt-4o-2024-05-13_07_03_2024_00_17_44/result_summary.json` to view the evaluation results. The full dialog of each scenario is stored within a `trajectories` subdirectory, e.g. `data/agent_gpt-4o-2024-05-13_user_gpt-4o-2024-05-13_07_03_2024_00_17_44/trajectories/wifi_off/conversation.json`.

#### Hosting open source models
Open source models can be hosted using [vLLM's OpenAI Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html). At the time of writing this the latest version was [0.5.0.post1](https://github.com/vllm-project/vllm/releases/tag/v0.5.0.post1). Here is an example to serve the `gorilla-llm/gorilla-openfunctions-v2` model:
```
pip install vllm
python3 -m vllm.entrypoints.openai.api_server --model gorilla-llm/gorilla-openfunctions-v2
```
Note that when serving a model for the first time it may be necessary to set the Hugging Face token using the `HF_TOKEN` environment variable:
```
env HF_TOKEN=<YOUR_HF_TOKEN> python3 -m vllm.entrypoints.openai.api_server --model gorilla-llm/gorilla-openfunctions-v2
```
Depending on your GPU you may have to explicitly set the `dtype` with e.g. `--dtype=half`. By default, the above command will host an OpenAI compatible server at http://0.0.0.0:8000. The following lines of Python code can be used to quickly test that the server can be reached:
```python
import openai
openai_client = openai.OpenAI(api_key="EMPTY", base_url="http://0.0.0.0:8000/v1")
print(openai_client.models.list())
```
On success, this should print the models hosted by the server. Note that these instructions assume that the client and server run on the same compute instance. If the server is running on a different compute instance, the compute instance running the client can use SSH port forwarding to access the server. This example runs a single scenario using the `Gorilla` agent:
```
env OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>  OPENAI_BASE_URL="http://0.0.0.0:8000/v1" tool_sandbox --agent Gorilla -s wifi_off
```

#### Example command for running all scenarios
By default, if `--scenario` is not provided all scenarios will be executed. Here is an example command using GPT-4o as both the user simulator and agent:
```
env OPENAI_API_KEY=<YOUR_OPENAI_API_KEY> RAPID_API_KEY=<YOUR_RAPID_API_KEY> tool_sandbox --user GPT_4_o_2024_05_13 --agent GPT_4_o_2024_05_13
```
Notebooks for introspecting and comparing the results can be found [here](tool_sandbox%2Fnotebooks).

#### Development setup
1. Setup pre-commit hooks. Includes multiple linters
```bash
pre-commit install --hook-type pre-commit
```

2. If some hooks are too slow and you would wish to skip them, you can do so with `SKIP` env variable. For example
```bash
SKIP="mypy" git commit -m "temporary commit that might not pass mypy"
```

## Documentation

The following sections introduce the core design and concepts.

### Execution context
The execution context stores the complete state of the tool sandbox. More specifically, the tools, dialog history between the different roles and the world state. It also stores a snapshot of the state at every turn, which is used for introspection and evaluation. The world state consists of:
- a settings database (e.g. cellular service status, WiFi status)
- a contact book
- a messaging database (storing text messages that have been "sent")
- a reminder database (storing reminders that have been created)

### Tools
The implemented tools are a set of highly composable, explicitly or implicitly dependent Python functions, creating complex reasoning challenges. Tools can manipulate the world state through the execution context. Here is an example tool:
```
@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def remove_contact(person_id: str) -> None:
    """Remove an existing contact person to contact database.

    Args:
        person_id:      String format unique identifier of the person to be deleted

    Returns:

    Raises:
        NoDataError:    If the provided person_id was not found
    """
    validate_type(person_id, "person_id", str)

    current_context = get_current_context()
    current_context.remove_from_database(
        namespace=DatabaseNamespace.CONTACT, predicate=pl.col("person_id") == person_id
    )
```
A Python function is registered as a tool with the `register_as_tool` decorator. Note that when defining a scenario the developer can decide which tools should be visible to the agent. You can find the available tools [here](tool_sandbox%2Ftools).

### Roles
The roles interacting in the tool sandbox are the system, user, agent and execution environment. This is more generic than the usual chat and agent roles commonly used in proprietary APIs. The interaction between the roles is based on a message passing system. Each message specifies the sender, recipient and to which roles it is visible to.

#### User
The user represents a human interacting with an agent hoping to complete a task. The user role decides when the task is complete by using the `end_conversation` tool, which is the only tool available to the user. The user can be a real human or it can be simulated by an agent.

#### Agent
The agent initially receives a message from the user in natural language specifying the task to be completed. The agent can then decide to respond to the user (e.g. asking for clarification) or send a tool use request to the execution environment. These agents have been implemented:
- Claude Opus, Sonnet, Haiku ([Anthropic](https://www.anthropic.com/claude))
- Command R and Command R Plus ([Cohere](https://cohere.com/command))
- Gemini ([Google](https://deepmind.google/technologies/gemini/))
- Gorilla ([UC Berkeley](https://gorilla.cs.berkeley.edu))
- GPT ([OpenAI](https://platform.openai.com/docs/models))
- Human via CLI

The agents are defined [here](tool_sandbox%2Froles).

#### Execution environment
The execution environment executes tool calls requested by the agent. The implementation is based on Python's [code.InteractiveConsole](https://docs.python.org/3.9/library/code.html#code.InteractiveConsole) module. The tool result is captured via `stdout` and potential exceptions are captured via `stderr`. This is similar to executing code in a Jupyter notebook. If an exception occurs it is communicated back to the agent such that it can refine its tool call and try again.
Note that the code is executed directly on the host machine and not in e.g. a sandbox like a docker container. At the moment this is acceptable since
- we do not allow the agent to run arbitrary Python code, but it can only select from the tools we have implemented
- we have full control over which tools exist and how they are implemented

However, with the current implementation a developer could get quite sad if we added a new `rm_dir` tool and the agent requests a tool call like `rm_dir("/")`.

### Scenario
Scenarios are defined in Python as extensions to a base setup. One can think of the base setup as the initial device state.
```
ScenarioExtension(
    name="cellular_off",
    base_scenario=base_scenarios["base"],
    messages=[
        {
            "sender": RoleType.SYSTEM,
            "recipient": RoleType.USER,
            "content": USER_INSTRUCTION + "Turn off cellular service",
        },
        {
            "sender": RoleType.USER,
            "recipient": RoleType.AGENT,
            "content": "Turn off cellular",
        },
    ],
    tool_allow_list=["set_cellular_service_status"],
    milestones=[
        Milestone(
            snapshot_constraints=[
                SnapshotConstraint(
                    database_namespace=DatabaseNamespace.SETTING,
                    snapshot_constraint=snapshot_similarity,
                    target_dataframe=pl.DataFrame(
                        {
                            "cellular": False,
                        }
                    ),
                )
            ]
        ),
        Milestone(
            snapshot_constraints=[
                SnapshotConstraint(
                    database_namespace=DatabaseNamespace.SANDBOX,
                    snapshot_constraint=snapshot_similarity,
                    target_dataframe=pl.DataFrame(
                        {
                            "sender": RoleType.AGENT,
                            "recipient": RoleType.USER,
                            "content": "Cellular service is turned off",
                        }
                    ),
                )
            ]
        ),
    ],
)
```
#### Tool augmentations
Note that several tool augmentations are supported:
- adding tools not needed to complete the task (distraction tools)
- scrambling the tool name (i.e. renaming the tool to something less informative `set_cellular_service_status` to `settings_0` forcing the agent to use the docstring when deciding which tool to use)
- removing the argument descriptions of the tools
- renaming the arguments in the docstring (e.g. `arg_0` instead of `phone_number`)
- removing the argument type hints forcing the agent to guess the data type or figuring it out through trial and error

#### Scenario categories
The scenarios are categorized in order to gain insight into what agents can handle well. Note that a scenario can belong to multiple categories at the same time. The categories are:
- Single/multiple tool call. This is based on how many tool uses are needed to achieve the task.
- Single/multiple user turn. If a user provides all necessary information in the initial message to the agent then the scenario is considered a single turn scenario.
- State dependency. These are categories where successful tool execution depends on the world state (e.g. enabling some setting using another tool before being able to use the tool to perform the user's task). In these cases there is an implicit dependency between tools / a tool and the world state, which the agent needs to discover through trial and error.
- Canonicalization. This category is for scenarios where natural language information needs to be transformed into its corresponding canonical form. In some cases the agent can directly do this (e.g. converting `1k` to `1000`), but in other cases it requires a tool (e.g. converting `this Friday` to `14th of June 2024`).
- Insufficient information. In these scenarios necessary tools or information are held back on purpose such that the agent is unable to perform the user's task. The motivation is to see if the agent can identify that it is unable to complete the task or if it instead hallucinates tools or tool arguments.

### Evaluation

Many different trajectories could lead to the same outcome. There could be different tools that can complete the task,
the agent could fail to complete and ask the user for additional input, or figure things out with the execution environment
through trial and error. This makes evaluation extra difficult for an interactive environment. However, between all these
possibilities, there's often a few **_critical milestones_** we need to hit in order to complete the task.

For example, suppose
1. The user's cellular service is currently off
2. The user wants to send a message to Fredrik Thordendal saying: 'How's the new album coming along.'.

Given the tools available to us, we know a few things must happen in the following order to achieve the goal:

0. **_First_**, at some point, the cellular status in SETTINGS database should be `True` **_exactly_**
1. **_Parallel to 0_**, agent must make a tool call to with `search_contacts` tool and `{"name": "Fredrik Thordendal"}` argument **_exactly_**
2. **_After 0 & 1_**, the MESSAGING database should contain a message
   1. from the phone number +12453344098 **_exactly_**
   2. saying **_something close to_** How's the new album coming along.
3. **_After 2_**, agent should confirm to the user that the message has been sent, saying **_something close to_** `"Your message to Fredrik Thordendal has been sent saying: How's the new album coming along"`

We don't know exactly when these milestones shall happen, but we know they must happen in this order at some point
in the trajectory. This is the general design principle of our evaluation. To make this a little more formal


1. Evaluation criteria is defined with a Milestone DAG. Directional edges define the sequential order of each milestone.
   In the example above, the edges would be `[(0, 2), (1, 2), (2, 3)]`
2. Each milestone contains multiple similarity measures, calculating the [0, 1] similarity between this milestone
   and each step in the trajectory. Similarity measures are allowed to depend on other milestones. These similarities include:
   1. snapshot_similarity: How close is a database to a target database
   2. addition_similarity: How close is a database to a target database, if the target database was derived from adding
      k target rows into a reference database
   3. removal_similarity: How close is a database to a target database, if the target database was derived from removing
      k target rows from a reference database
   4. update_similarity: How close is a database to a target database, if the target database was derived from updating
      k target rows in a reference database
   5. tool_trace_dependant_similarity: How close is a database to a target database, if the target database includes
      values extracted from the tool_trace of a reference database
   6. guardrail_similarity: The database should be identical to a reference database, otherwise this similarity is 0
3. Each milestone similarity further breaks down into column-wise similarity, which can be **_exact_match_**, **_rouge_l_**
   etc. Allowing for more customization in matching logic
4. Milestone similarity is derived by calculating the geometric mean of all its similarity measures.
   1. Geo mean ensures if 1 exact matching similarity returns 0, the whole milestone similarity is 0.
5. An optimal match between milestones and trajectory is found by maximizing the arithmetic mean of all milestone similarities
   under the constraint that matched milestone order should be one possible topological sort of the Milestone DAG.

The milestones in the example above can be described as follows

```python
milestones = [
    Milestone(
        snapshot_constraints=[
            SnapshotConstraint(
                database_namespace=DatabaseNamespace.SETTING,
                snapshot_constraint=snapshot_similarity,
                target_dataframe=pl.DataFrame(
                    {
                        "cellular": True,
                    }
                ),
            )
        ]
    ),
    Milestone(
        snapshot_constraints=[
            SnapshotConstraint(
                database_namespace=DatabaseNamespace.SANDBOX,
                snapshot_constraint=snapshot_similarity,
                target_dataframe=pl.DataFrame(
                    {
                        "sender": RoleType.AGENT,
                        "recipient": RoleType.EXECUTION_ENVIRONMENT,
                        "tool_trace": json.dumps(
                            {
                                "tool_name": "search_contacts",
                                "arguments": {"name": "Fredrik Thordendal"},
                            },
                            ensure_ascii=False,
                        ),
                    }
                ),
            )
        ]
    ),
    Milestone(
        snapshot_constraints=[
            SnapshotConstraint(
                database_namespace=DatabaseNamespace.MESSAGING,
                snapshot_constraint=addition_similarity,
                target_dataframe=pl.DataFrame(
                    {
                        "recipient_phone_number": "+12453344098",
                        "content": "How's the new album coming along",
                    },
                ),
                reference_milestone_node_index=0,
            )
        ]
    ),
    Milestone(
        snapshot_constraints=[
            SnapshotConstraint(
                database_namespace=DatabaseNamespace.SANDBOX,
                snapshot_constraint=snapshot_similarity,
                target_dataframe=pl.DataFrame(
                    {
                        "sender": RoleType.AGENT,
                        "recipient": RoleType.USER,
                        "content": "Your message to Fredrik Thordendal has been sent saying: "
                                   "How's the new album coming along",
                    }
                ),
            )
        ]
    ),
]
# search_contacts and set_cellular_service_status can happen in any order
edge_list = [(0, 2), (1, 2), (2, 3)]
```
Here's an example trajectory collected from `gpt-3.5-turbo-0125`, as well as the evaluation results
```
shape: (15, 5)
+-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------+
| sandbox_message_index | sender                | recipient             | content                                  | tool_trace                              |
| ---                   | ---                   | ---                   | ---                                      | ---                                     |
| i32                   | enum                  | enum                  | str                                      | list[str]                               |
+============================================================================================================================================================+
| 0                     | SYSTEM                | EXECUTION_ENVIRONMENT | import json                              | null                                    |
|                       |                       |                       | from tool_sandbox.tools.contact import   |                                         |
|                       |                       |                       | add_contact, modify_contact,             |                                         |
|                       |                       |                       | remove_contact, search_contacts          |                                         |
|                       |                       |                       | from tool_sandbox.tools.setting import   |                                         |
|                       |                       |                       | get_cellular_service_status,             |                                         |
|                       |                       |                       | get_current_location, get_wifi_status,   |                                         |
|                       |                       |                       | set_cellular_service_status,             |                                         |
|                       |                       |                       | set_wifi_status                          |                                         |
|                       |                       |                       | from tool_sandbox.tools.messaging        |                                         |
|                       |                       |                       | import search_messages,                  |                                         |
|                       |                       |                       | send_message_with_phone_number           |                                         |
|                       |                       |                       | from tool_sandbox.tools.reminder import  |                                         |
|                       |                       |                       | add_reminder, modify_reminder,           |                                         |
|                       |                       |                       | remove_reminder, search_reminder         |                                         |
|                       |                       |                       | from tool_sandbox.tools.search_tools     |                                         |
|                       |                       |                       | import convert_currency,                 |                                         |
|                       |                       |                       | knowledge_base_question_answering,       |                                         |
|                       |                       |                       | search_dictionary, search_holiday,       |                                         |
|                       |                       |                       | search_lat_lon,                          |                                         |
|                       |                       |                       | search_location_around_lat_lon,          |                                         |
|                       |                       |                       | search_point_of_interest_around_lat_lon, |                                         |
|                       |                       |                       | search_stock,                            |                                         |
|                       |                       |                       | search_weather_around_lat_lon            |                                         |
|                       |                       |                       | from tool_sandbox.tools.user_tools       |                                         |
|                       |                       |                       | import end_conversation                  |                                         |
|                       |                       |                       | from tool_sandbox.tools.utilities        |                                         |
|                       |                       |                       | import datetime_info_to_timestamp,       |                                         |
|                       |                       |                       | get_current_timestamp,                   |                                         |
|                       |                       |                       | seconds_to_hours_minutes_seconds,        |                                         |
|                       |                       |                       | shift_timestamp, timestamp_diff,         |                                         |
|                       |                       |                       | timestamp_to_datetime_info,              |                                         |
|                       |                       |                       | unit_conversion                          |                                         |
|                       |                       |                       |                                          |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 1                     | SYSTEM                | AGENT                 | Don't make assumptions about what values | null                                    |
|                       |                       |                       | to plug into functions. Ask for          |                                         |
|                       |                       |                       | clarification if a user request is       |                                         |
|                       |                       |                       | ambiguous.                               |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 2                     | SYSTEM                | USER                  | You are no longer an assistant. Assume   | null                                    |
|                       |                       |                       | that you are a User talking to a virtual |                                         |
|                       |                       |                       | assistant. Answer any question the       |                                         |
|                       |                       |                       | virtual assistant asks you accurately.   |                                         |
|                       |                       |                       | You are a lazy user, so be less verbose  |                                         |
|                       |                       |                       | and only provide 1 piece of information  |                                         |
|                       |                       |                       | at a time. Keep trying to ask the        |                                         |
|                       |                       |                       | assistant to complete the task when it   |                                         |
|                       |                       |                       | claims it couldn't do so by providing    |                                         |
|                       |                       |                       | more instructions. Ask it to use the     |                                         |
|                       |                       |                       | tools it has access to to resolve any    |                                         |
|                       |                       |                       | issues it encountered at least 5 times.  |                                         |
|                       |                       |                       | Use only the information provided. Do    |                                         |
|                       |                       |                       | not make up false information. DO NOT    |                                         |
|                       |                       |                       | fall back to assistant behavior. When    |                                         |
|                       |                       |                       | you feel the assistant have completed    |                                         |
|                       |                       |                       | your task, or it still cannot complete   |                                         |
|                       |                       |                       | the request after 5 tries, use the       |                                         |
|                       |                       |                       | provided tool named `end_conversation`   |                                         |
|                       |                       |                       | to stop the conversation. The task you   |                                         |
|                       |                       |                       | would like to complete is: Send a        |                                         |
|                       |                       |                       | message to Fredrik Thordendal saying:    |                                         |
|                       |                       |                       | How's the new album coming along         |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 3                     | USER                  | AGENT                 | Send a message to Fredrik Thordendal     | null                                    |
|                       |                       |                       | saying: "How's the new album coming      |                                         |
|                       |                       |                       | along." Resolve any issue by yourself.   |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 4                     | AGENT                 | EXECUTION_ENVIRONMENT | call_LbXHvh2I1ibGcoy89hHDhsWQ_parameters | ["{"tool_name": "search_contacts",      |
|                       |                       |                       | = {'name': 'Fredrik Thordendal'}         | "arguments": {"name": "Fredrik          |
|                       |                       |                       | call_LbXHvh2I1ibGcoy89hHDhsWQ_response = | Thordendal"}, "result": [{"person_id":  |
|                       |                       |                       | search_contacts(**call_LbXHvh2I1ibGcoy89 | "9e137f06-916a-5310-8174-cf0b7e9f7054", |
|                       |                       |                       | hHDhsWQ_parameters)                      | "name": "Fredrik Thordendal",           |
|                       |                       |                       | print(repr(call_LbXHvh2I1ibGcoy89hHDhsWQ | "phone_number": "+12453344098",         |
|                       |                       |                       | _response))                              | "relationship": "friend", "is_self":    |
|                       |                       |                       |                                          | false}]}"]                              |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 5                     | EXECUTION_ENVIRONMENT | AGENT                 | [{'person_id':                           | null                                    |
|                       |                       |                       | '9e137f06-916a-5310-8174-cf0b7e9f7054',  |                                         |
|                       |                       |                       | 'name': 'Fredrik Thordendal',            |                                         |
|                       |                       |                       | 'phone_number': '+12453344098',          |                                         |
|                       |                       |                       | 'relationship': 'friend', 'is_self':     |                                         |
|                       |                       |                       | False}]                                  |                                         |
|                       |                       |                       |                                          |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 6                     | AGENT                 | EXECUTION_ENVIRONMENT | call_oHPoWYuTxkuKRojfGI5Ro4ML_parameters | null                                    |
|                       |                       |                       | = {'phone_number': '+12453344098',       |                                         |
|                       |                       |                       | 'content': "How's the new album coming   |                                         |
|                       |                       |                       | along."}                                 |                                         |
|                       |                       |                       | call_oHPoWYuTxkuKRojfGI5Ro4ML_response = |                                         |
|                       |                       |                       | send_message_with_phone_number(**call_oH |                                         |
|                       |                       |                       | PoWYuTxkuKRojfGI5Ro4ML_parameters)       |                                         |
|                       |                       |                       | print(repr(call_oHPoWYuTxkuKRojfGI5Ro4ML |                                         |
|                       |                       |                       | _response))                              |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 7                     | EXECUTION_ENVIRONMENT | AGENT                 | Traceback (most recent call last):       | null                                    |
|                       |                       |                       |   File "<string>", line 2, in <module>   |                                         |
|                       |                       |                       | File "/opt/anaconda3/envs/tool-sandbox/ |                                         |
|                       |                       |                       | lib/python3.9/site-packages/decorator.py |                                         |
|                       |                       |                       | ", line 232, in fun                      |                                         |
|                       |                       |                       | return caller(func, *(extras + args),    |                                         |
|                       |                       |                       | **kw)                                    |                                         |
|                       |                       |                       | File "ToolSandbox/                       |                                         |
|                       |                       |                       | tool_sandbox/common/utils.py", line      |                                         |
|                       |                       |                       | 361, in _f                               |                                         |
|                       |                       |                       |     result = f(*args, **kwargs)          |                                         |
|                       |                       |                       | File "ToolSandbox/                       |                                         |
|                       |                       |                       | tool_sandbox/tools/messaging.py", line   |                                         |
|                       |                       |                       | 51, in send_message_with_phone_number    |                                         |
|                       |                       |                       | raise ConnectionError("Cellular service  |                                         |
|                       |                       |                       | is not enabled")                         |                                         |
|                       |                       |                       | ConnectionError: Cellular service is not |                                         |
|                       |                       |                       | enabled                                  |                                         |
|                       |                       |                       |                                          |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 8                     | AGENT                 | EXECUTION_ENVIRONMENT | call_AbZtI4fkAAUwoonIDbcW2Vu3_parameters | ["{"tool_name":                         |
|                       |                       |                       | = {'on': True}                           | "set_cellular_service_status",          |
|                       |                       |                       | call_AbZtI4fkAAUwoonIDbcW2Vu3_response = | "arguments": {"on": true}, "result":    |
|                       |                       |                       | set_cellular_service_status(**call_AbZtI | null}"]                                 |
|                       |                       |                       | 4fkAAUwoonIDbcW2Vu3_parameters)          |                                         |
|                       |                       |                       | print(repr(call_AbZtI4fkAAUwoonIDbcW2Vu3 |                                         |
|                       |                       |                       | _response))                              |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 9                     | EXECUTION_ENVIRONMENT | AGENT                 | None                                     | null                                    |
|                       |                       |                       |                                          |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 10                    | AGENT                 | EXECUTION_ENVIRONMENT | call_5GE8RMyJbqoNWXIPJZbbq7L9_parameters | ["{"tool_name":                         |
|                       |                       |                       | = {'phone_number': '+12453344098',       | "send_message_with_phone_number",       |
|                       |                       |                       | 'content': "How's the new album coming   | "arguments": {"phone_number":           |
|                       |                       |                       | along."}                                 | "+12453344098", "content": "How's the   |
|                       |                       |                       | call_5GE8RMyJbqoNWXIPJZbbq7L9_response = | new album coming along."}, "result":    |
|                       |                       |                       | send_message_with_phone_number(**call_5G | "8a0ce99b-f2ee-4c47-9bb5-54e379b2233a"} |
|                       |                       |                       | E8RMyJbqoNWXIPJZbbq7L9_parameters)       | "]                                      |
|                       |                       |                       | print(repr(call_5GE8RMyJbqoNWXIPJZbbq7L9 |                                         |
|                       |                       |                       | _response))                              |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 11                    | EXECUTION_ENVIRONMENT | AGENT                 | '8a0ce99b-f2ee-4c47-9bb5-54e379b2233a'   | null                                    |
|                       |                       |                       |                                          |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 12                    | AGENT                 | USER                  | Message has been successfully sent to    | null                                    |
|                       |                       |                       | Fredrik Thordendal asking: "How's the    |                                         |
|                       |                       |                       | new album coming along."                 |                                         |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 13                    | USER                  | EXECUTION_ENVIRONMENT | end_conversation()                       | ["{"tool_name": "end_conversation",     |
|                       |                       |                       |                                          | "arguments": {}, "result": null}"]      |
|-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------|
| 14                    | EXECUTION_ENVIRONMENT | USER                  |                                          | null                                    |
+-----------------------+-----------------------+-----------------------+------------------------------------------+-----------------------------------------+
```

`milestone_mapping` contains a dictionary of `milestone_indx: (corresponding_turn_index, milestone_similarity)`
```json
{
   "name": "send_message_with_contact_content_cellular_off",
   "categories": [
       "STATE_DEPENDENCY",
       "MULTIPLE_TOOL_CALL",
       "SINGLE_USER_TURN",
       "NO_DISTRACTION_TOOLS"
   ],
   "similarity": 0.9706467684812784,
   "turn_count": 12,
   "milestone_mapping": {
       "1": [
           4,
           1.0
       ],
       "0": [
           9,
           1.0
       ],
       "2": [
           11,
           1.0
       ],
       "3": [
           12,
           0.8825870739251136
       ]
   }
}
```


## Citation

To cite _ToolSandbox_:
```text
@misc{lu2024toolsandboxstatefulconversationalinteractive,
      title={ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities}, 
      author={Jiarui Lu and Thomas Holleis and Yizhe Zhang and Bernhard Aumayer and Feng Nan and Felix Bai and Shuang Ma and Shen Ma and Mengyu Li and Guoli Yin and Zirui Wang and Ruoming Pang},
      year={2024},
      eprint={2408.04682},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2408.04682}, 
}
```
