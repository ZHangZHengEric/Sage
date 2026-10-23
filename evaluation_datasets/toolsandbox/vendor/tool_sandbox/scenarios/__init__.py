# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
import copy
import random
from typing import Dict, Set, cast

import tool_sandbox.tools
from tool_sandbox.common.execution_context import ScenarioCategories
from tool_sandbox.common.scenario import Scenario
from tool_sandbox.common.tool_discovery import ToolBackend, rank_tools_by_similarity
from tool_sandbox.scenarios.insufficient_information_scenarios import (
    named_insufficient_information_scenarios,
)
from tool_sandbox.scenarios.multiple_tool_call_scenarios import (
    named_multiple_tool_call_scenarios,
)
from tool_sandbox.scenarios.multiple_user_turn_scenarios import (
    named_multiple_user_turn_scenarios,
)
from tool_sandbox.scenarios.single_tool_call_scenarios import (
    named_single_tool_call_scenarios,
)


def named_scenarios(
    preferred_tool_backend: ToolBackend,
) -> Dict[str, Scenario]:
    """Aggregate named scenarios from submodules

    In addition, adds tool augmentation scenarios for all

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A dictionary of scenarios
    """
    scenarios: Dict[str, Scenario] = dict()
    for new_scenarios in [
        named_single_tool_call_scenarios(preferred_tool_backend=preferred_tool_backend),
        named_multiple_tool_call_scenarios(
            preferred_tool_backend=preferred_tool_backend
        ),
        named_multiple_user_turn_scenarios(
            preferred_tool_backend=preferred_tool_backend
        ),
        named_insufficient_information_scenarios(
            preferred_tool_backend=preferred_tool_backend
        ),
    ]:
        conflicting_names: Set[str] = set(scenarios.keys()) & set(new_scenarios.keys())
        if conflicting_names:
            raise ValueError(
                f"Conflicting names found between scenarios: {conflicting_names}"
            )
        scenarios.update(new_scenarios)
    # Add tool augmentations
    names = list(scenarios.keys())
    for name in names:
        similar_tools = rank_tools_by_similarity(
            scenarios[name].starting_context.tool_allow_list,
            tool_sandbox.tools,
            preferred_tool_backend=preferred_tool_backend,
        )
        # Shuffle base scenario tools
        assert scenarios[name].starting_context.tool_allow_list is not None
        random.shuffle(
            cast(list[str], scenarios[name].starting_context.tool_allow_list)
        )

        # 3 distraction
        scenario = copy.deepcopy(scenarios[name])
        assert scenario.starting_context.tool_allow_list is not None
        scenario.starting_context.tool_allow_list.extend(similar_tools[:3])
        random.shuffle(scenario.starting_context.tool_allow_list)
        scenario.categories.append(ScenarioCategories.THREE_DISTRACTION_TOOLS)
        scenarios[f"{name}_3_distraction_tools"] = scenario

        # 10 distraction
        scenario = copy.deepcopy(scenarios[name])
        assert scenario.starting_context.tool_allow_list is not None
        scenario.starting_context.tool_allow_list.extend(similar_tools[:10])
        random.shuffle(scenario.starting_context.tool_allow_list)
        scenario.categories.append(ScenarioCategories.TEN_DISTRACTION_TOOLS)
        scenarios[f"{name}_10_distraction_tools"] = scenario

        # All tools
        scenario = copy.deepcopy(scenarios[name])
        assert scenario.starting_context.tool_allow_list is not None
        scenario.starting_context.tool_allow_list.extend(similar_tools)
        random.shuffle(scenario.starting_context.tool_allow_list)
        scenario.categories.append(ScenarioCategories.ALL_TOOLS_AVAILABLE)
        scenarios[f"{name}_all_tools"] = scenario

        # No distraction. This is already there. Just add the tag
        scenarios[name].categories.append(ScenarioCategories.NO_DISTRACTION_TOOLS)

        # On top of 3 distraction, add tool augmentations
        # Scramble description
        scenario = copy.deepcopy(scenarios[f"{name}_3_distraction_tools"])
        scenario.starting_context.tool_augmentation_list = [
            ScenarioCategories.TOOL_DESCRIPTION_SCRAMBLED
        ]
        scenario.categories.append(ScenarioCategories.TOOL_DESCRIPTION_SCRAMBLED)
        scenarios[f"{name}_3_distraction_tools_tool_description_scrambled"] = scenario

        # Scramble arg type
        scenario = copy.deepcopy(scenarios[f"{name}_3_distraction_tools"])
        scenario.starting_context.tool_augmentation_list = [
            ScenarioCategories.ARG_TYPE_SCRAMBLED
        ]
        scenario.categories.append(ScenarioCategories.ARG_TYPE_SCRAMBLED)
        scenarios[f"{name}_3_distraction_tools_arg_type_scrambled"] = scenario

        # Scramble arg description
        scenario = copy.deepcopy(scenarios[f"{name}_3_distraction_tools"])
        scenario.starting_context.tool_augmentation_list = [
            ScenarioCategories.ARG_DESCRIPTION_SCRAMBLED
        ]
        scenario.categories.append(ScenarioCategories.ARG_DESCRIPTION_SCRAMBLED)
        scenarios[f"{name}_3_distraction_tools_arg_description_scrambled"] = scenario

        # Scramble tool name
        scenario = copy.deepcopy(scenarios[f"{name}_3_distraction_tools"])
        scenario.starting_context.tool_augmentation_list = [
            ScenarioCategories.TOOL_NAME_SCRAMBLED
        ]
        scenario.categories.append(ScenarioCategories.TOOL_NAME_SCRAMBLED)
        scenarios[f"{name}_3_distraction_tools_tool_name_scrambled"] = scenario

    return scenarios
