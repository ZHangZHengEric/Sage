# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Test case scenarios"""

import copy
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, cast

import polars as pl
from attrs import Factory, define
from tqdm import tqdm

from tool_sandbox.common.evaluation import (
    Evaluation,
    EvaluationResult,
    Milestone,
    MilestoneMatcher,
    Minefield,
)
from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    ExecutionContext,
    RoleType,
    ScenarioCategories,
    get_current_context,
    set_current_context,
)
from tool_sandbox.common.message_conversion import serialize_to_conversation
from tool_sandbox.roles.base_role import BaseRole


@define
class ScenarioResult:
    """Output of Scenario Play, saving both the execution context after the rollout is collected,
    and evaluation result

    """

    ending_context: ExecutionContext
    evaluation_result: EvaluationResult


@define
class Scenario:
    """Test case scenarios that defines a test case
    Each scenario contains an execution context defining starting state, and an evaluation object defining
    evaluation criteria
    """

    # Initial context, contains initial world state
    starting_context: ExecutionContext = Factory(ExecutionContext)
    # Evaluation definition
    evaluation: Evaluation = Factory(Evaluation)
    # Max number of total messages in roll out
    max_messages: int = 30
    # Category tags
    categories: List[ScenarioCategories] = Factory(list)

    def play(
        self, roles: Dict[RoleType, BaseRole], scenario_name: str
    ) -> ExecutionContext:
        """Play out the scenario and return execution context

        Args:
            roles:  A mapping indicating which Role we should use for each role type
            scenario_name: The scenario name.

        Returns:
            Execution context after playing out the scenario

        """
        execution_context = copy.deepcopy(self.starting_context)

        set_current_context(execution_context)
        # Prepare InteractiveConsole by consuming system message addressed to it
        sandbox_db = execution_context.get_database(
            DatabaseNamespace.SANDBOX,
            drop_sandbox_message_index=False,
            get_all_history_snapshots=True,
        )
        max_sandbox_message_index = execution_context.max_sandbox_message_index
        for message_index in range(max_sandbox_message_index + 1):
            if (
                sandbox_db["recipient"][message_index] == RoleType.EXECUTION_ENVIRONMENT
                and sandbox_db["sender"][message_index] == RoleType.SYSTEM
            ):
                roles[sandbox_db["recipient"][message_index]].respond(
                    ending_index=message_index
                )
        # Since this should only be processing system message, there should be no new messages after this
        assert (
            get_current_context().max_sandbox_message_index == max_sandbox_message_index
        )
        # Start processing non-system messages
        with tqdm(total=self.max_messages, desc=scenario_name) as pbar:
            while (
                sandbox_db["conversation_active"][-1]
                and sandbox_db["sandbox_message_index"][-1]
                < self.max_messages + max_sandbox_message_index
            ):
                roles[sandbox_db["recipient"][-1]].respond()
                sandbox_db = get_current_context().get_database(
                    DatabaseNamespace.SANDBOX, drop_sandbox_message_index=False
                )
                pbar.update(1)
            # Update max turns on successful end.
            pbar.total = pbar.n
            pbar.update(0)

        return get_current_context()

    def play_and_evaluate(
        self,
        roles: Dict[RoleType, BaseRole],
        output_directory: Path,
        scenario_name: str,
    ) -> ScenarioResult:
        """Play out the scenario and evaluate according to evaluation

        Args:
            roles:                      A mapping indicating which Role we should use for each role type
            output_directory:           Directory to write results to
            scenario_name:              Unique name for scenario. Used to serialize message history

        Returns:
            A ScenarioResult object containing the final execution context and evaluation result
            If play failed due to errors, return None object

        """
        # Prepare directories
        scenario_output_directory: Path = (
            output_directory / "trajectories" / scenario_name
        )
        scenario_output_directory.mkdir(exist_ok=True, parents=True)

        # If an exception occurs during playback we want to save the conversation and
        # execution context histories before re-raising the exception to skip
        # evaluation.
        try:
            self.play(roles=roles, scenario_name=scenario_name)
        except Exception:
            raise
        finally:
            execution_context = get_current_context()

            # Write pretty print messages
            # Skip user simulator few shot messages
            pretty_print_str = (
                "Note that User Simulator few shot messages have been omitted\n"
                + str(
                    execution_context.get_database(
                        DatabaseNamespace.SANDBOX,
                        get_all_history_snapshots=True,
                        drop_sandbox_message_index=False,
                    )
                    .filter(
                        (pl.col("visible_to") != [RoleType.USER])
                        | (pl.col("visible_to").is_null())
                    )
                    .drop(
                        [
                            "openai_tool_call_id",
                            "conversation_active",
                        ]
                    )
                )
            )
            with open(
                scenario_output_directory / "pretty_print.txt", "w", encoding="utf-8"
            ) as f:
                f.write(pretty_print_str)
            # Write execution_context
            with open(
                scenario_output_directory / "execution_context.json",
                "w",
                encoding="utf-8",
            ) as f:
                # We'll have to ditch dill InteractiveConsole here because
                # dill creates a bytes instead of raw string
                f.write(
                    json.dumps(
                        execution_context.to_dict(serialize_console=False),
                        ensure_ascii=False,
                        indent=4,
                    )
                )

        evaluation_result = self.evaluation.evaluate(
            execution_context=execution_context, max_turn_count=self.max_messages
        )

        # Write the conversation to a JSON file.
        conversation = serialize_to_conversation(
            execution_context=execution_context,
            evaluation_result=evaluation_result,
            milestones=cast(
                list[Milestone], self.evaluation.milestone_matcher.milestones
            ),
            minefields=cast(
                list[Minefield], self.evaluation.minefield_matcher.milestones
            ),
        )
        with open(
            scenario_output_directory / "conversation.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)
        return ScenarioResult(
            ending_context=execution_context,
            evaluation_result=evaluation_result,
        )


@define
class ScenarioExtension:
    """Extends a few fields over base scenario to form a valid test scenario"""

    # Name for the resulting extended scenario
    name: str
    # Base scenario to extend on
    base_scenario: Scenario
    # Messages to extend to the starting context of base scenario
    messages: list[dict[str, Union[str, list[RoleType]]]] = Factory(list)
    # Tool allow list to extend to starting context of base scenario
    tool_allow_list: Optional[List[str]] = None
    # Tool deny list to extend to starting context of base scenario
    tool_deny_list: Optional[List[str]] = None
    # Evaluation milestones to extend to the evaluation of base scenario
    milestones: List[Milestone] = Factory(list)
    # Optional edge list defining Milestone dependencies. If None, creates a linked list
    milestone_edge_list: Optional[List[Tuple[int, int]]] = None
    # Evaluation minefields to extend to the evaluation of base scenario
    minefields: List[Minefield] = Factory(list)
    # Optional edge list defining Minefield dependencies. If None, creates a linked list
    minefield_edge_list: Optional[List[Tuple[int, int]]] = None
    # Categories to extend to scenario
    categories: List[ScenarioCategories] = Factory(list)

    def get_extended_scenario(self) -> Dict[str, Scenario]:
        """Get an extended scenario based on specified extensions

        Returns:
            A dictionary containing extended scenario and name
        """
        scenario: Scenario = copy.deepcopy(self.base_scenario)
        scenario.starting_context.add_to_database(
            namespace=DatabaseNamespace.SANDBOX, rows=self.messages
        )
        if self.tool_allow_list is not None:
            if scenario.starting_context.tool_allow_list is None:
                scenario.starting_context.tool_allow_list = []
            scenario.starting_context.tool_allow_list.extend(self.tool_allow_list)
        if self.tool_deny_list is not None:
            if scenario.starting_context.tool_deny_list is None:
                scenario.starting_context.tool_deny_list = []
            scenario.starting_context.tool_deny_list.extend(self.tool_deny_list)
        scenario.evaluation = Evaluation(
            milestone_matcher=MilestoneMatcher(
                milestones=self.milestones, edge_list=self.milestone_edge_list
            ),
            minefield_matcher=MilestoneMatcher(
                milestones=self.minefields, edge_list=self.minefield_edge_list
            ),
        )

        scenario.categories.extend(self.categories)
        return {self.name: scenario}
