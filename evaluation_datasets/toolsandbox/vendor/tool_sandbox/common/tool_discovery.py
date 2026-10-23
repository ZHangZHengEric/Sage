# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
from collections import defaultdict
from enum import auto
from inspect import getmembers, getmodule, isfunction, ismodule
from types import ModuleType
from typing import Any, Callable, Iterable, Optional, Set

from rapidfuzz import fuzz, process, utils
from strenum import StrEnum


class ToolBackend(StrEnum):
    """Backend implementation of tools.

    This is used to resolve equivalently implemented tools with different backend.
    """

    DEFAULT = auto()


def get_all_tools(preferred_tool_backend: ToolBackend) -> dict[str, Callable[..., Any]]:
    """Get all registered tools.

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting
                                tool names.

    Returns:
        A dict of tool name to callable tools.
    """
    # We cannot import `tool_sandbox.tools` at the top due to a circular dependency.
    import tool_sandbox.tools

    return find_tools_by_module(tool_sandbox.tools, preferred_tool_backend)


def get_scrambled_tool_names(
    tools: Iterable[Callable[..., Any]],
) -> dict[str, str]:
    """Create a dictionary from actual to scrambled tool names.

    The scrambled tool name is computed as
    f"{module_name}_{per_module_function_counter}". For example, if there is a
    `rapid_api_search_tools` Python module containing two functions then the mapping
    will be:
     - `rapid_api_search_tools.search_stock`   -> `rapid_api_search_tools_0`
     - `rapid_api_search_tools.search_lat_lon` -> `rapid_api_search_tools_1`

    Args:
        tools:  All available tools.

    Returns:
        A dictionary from actual tool name to scrambled one.
    """
    module_name_to_fn_count: dict[str, int] = defaultdict(int)
    actual_to_scrambled_name = {}
    # We sort the tools alphabetically by module and function name. Technically, since
    # Python 3.7 dictionaries keep the insertion order and given that the tool discovery
    # with `find_tools_by_module` should be deterministic the tool ordering should thus
    # be deterministic as well. However, sorting is cheap and it makes human
    # introspection a bit nicer.
    for tool in sorted(tools, key=lambda tool: tool.__module__ + "." + tool.__name__):
        module_name = tool.__module__.split(".")[-1]
        scrambled_tool_name = f"{module_name}_{module_name_to_fn_count[module_name]}"
        actual_to_scrambled_name[tool.__name__] = scrambled_tool_name
        module_name_to_fn_count[module_name] += 1
    return actual_to_scrambled_name


def _extract_tools(
    function_name_and_callables: list[tuple[str, Callable[..., Any]]],
) -> dict[str, dict[ToolBackend, Callable[..., Any]]]:
    """Extract tools by name and backend from the given functions.

    When conflicting names with the same backend were found, raise KeyError.

    Args:
        function_name_and_callables:  List of function name and callable tuples.

    Returns:
        A dict of string name to Callable tools.

    Raises:
        KeyError: If multiple tools share the same name and backend
    """
    name_to_backend_to_tool: dict[str, dict[ToolBackend, Callable[..., Any]]] = (
        defaultdict(lambda: defaultdict())
    )
    for tool_name, tool in function_name_and_callables:
        backend_to_tool = name_to_backend_to_tool.get(tool_name, None)
        backend = getattr(tool, "backend", None)
        if (
            backend_to_tool is not None
            and backend is not None
            and backend_to_tool.get(backend, tool) != tool
        ):
            raise KeyError(
                f"Found 2 tools {tool} and {backend_to_tool.get(backend, tool)} "
                f"sharing the same name {tool_name} and backend {backend}"
            )
        if getattr(tool, "is_tool", False):
            name_to_backend_to_tool[tool_name][getattr(tool, "backend")] = tool
    return name_to_backend_to_tool


def find_tools_by_module(
    module: ModuleType, preferred_tool_backend: ToolBackend
) -> dict[str, Callable[..., Any]]:
    """Recursively look through modules / packages to find functions registered as tools.

    This will find any function registered with register_as_tool decorator that's under the module.

    When conflicting names with different backend were found, prefer the ones with
        execution_context.preferred_tool_backend, then DEFAULT, then anything else.

    When conflicting names with the same backend were found, raise KeyError.

    Args:
        module:                 If True, only return tools visible to the current role.
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A dict of string name to Callable tools.

    Raises:
        KeyError: If multiple tools share the same name and backend
    """
    current_module_name_and_functions: list[tuple[str, Callable[..., Any]]] = (
        getmembers(module, isfunction)
    )
    sub_module_name_and_tools: list[tuple[str, Callable[..., Any]]] = []
    for _, sub_module in getmembers(module, ismodule):
        # Recursively apply for submodules
        # Seems hacky, not sure if there's a better way to do this
        sub_module_name_and_tools.extend(
            list(find_tools_by_module(sub_module, preferred_tool_backend).items())
            if sub_module.__name__.startswith(module.__name__ + ".")
            else []
        )
    name_to_backend_to_tool = _extract_tools(
        sub_module_name_and_tools + current_module_name_and_functions
    )

    # Find preferred tool
    preferred_tools_by_name: dict[str, Callable[..., Any]] = defaultdict()
    backend_preferences = list(ToolBackend)
    # Move preferred_tool_backend and DEFAULT to the first 2 items in the list
    for item in [ToolBackend.DEFAULT, preferred_tool_backend]:
        backend_preferences.insert(
            0, backend_preferences.pop(backend_preferences.index(item))
        )
    for tool_name, backend_to_tool in name_to_backend_to_tool.items():
        preferred_tools_by_name[tool_name] = sorted(
            backend_to_tool.items(),
            key=lambda x: backend_preferences.index(getattr(x[1], "backend")),
        )[0][1]

    return preferred_tools_by_name


def rank_tools_by_similarity(
    target_tool_names: Optional[list[str]],
    module: ModuleType,
    preferred_tool_backend: ToolBackend,
) -> list[str]:
    """Given a list of tool names, return a list of all available tools in the module, ranked by their similarity
    to tool_names in descending order.

    Similarities are defined by a few heuristics. The returned list is broken down in to 2 sections
    1. tools in the same module as at least one of the tools in tool_names
    2. The rest
    Within each section, tools are sorted by the maximum fuzzy matching WRatio between its name and tool_names

    Args:
        target_tool_names:      Name of tools to get a ranked list for
        module:                 Module to find tools from
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.


    Returns:
        A list of tool names (excluding ones found in tool_names) sorted by descending similarity
    """
    all_tools = find_tools_by_module(
        module, preferred_tool_backend=preferred_tool_backend
    )
    # If not provided, return all tools
    if target_tool_names is None or not target_tool_names:
        return list(all_tools.keys())
    all_tools = find_tools_by_module(
        module, preferred_tool_backend=preferred_tool_backend
    )
    # Find the modules of provided tool
    target_module_names: Set[str] = set()
    for tool_name in target_tool_names:
        if tool_name not in all_tools:
            raise KeyError(f"{tool_name} cannot be found in module {module.__name__}")
        sub_module = getmodule(all_tools[tool_name])
        assert sub_module is not None
        target_module_names.add(sub_module.__name__)
    # Split tools in half
    same_module_tool_names: list[str] = []
    different_module_tool_names: list[str] = []
    for tool_name in all_tools:
        if tool_name not in target_tool_names:
            sub_module = getmodule(all_tools[tool_name])
            assert sub_module is not None
            if sub_module.__name__ in target_module_names:
                same_module_tool_names.append(tool_name)
            else:
                different_module_tool_names.append(tool_name)
    # Sort two sections
    same_module_tool_names = sorted(
        same_module_tool_names,
        key=lambda x: max(
            fuzzy_result[1]
            for fuzzy_result in process.extract(
                query=x,
                choices=target_tool_names,
                processor=utils.default_process,
                scorer=fuzz.WRatio,
            )
        ),
        reverse=True,
    )
    different_module_tool_names = sorted(
        different_module_tool_names,
        key=lambda x: max(
            fuzzy_result[1]
            for fuzzy_result in process.extract(
                query=x,
                choices=target_tool_names,
                processor=utils.default_process,
                scorer=fuzz.WRatio,
            )
        ),
        reverse=True,
    )
    return same_module_tool_names + different_module_tool_names
