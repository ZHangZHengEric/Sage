# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Taken from https://github.com/langchain-ai/langchain/blob/
90184255f880a26cbdffd7b764deae9be3242ece/libs/core/langchain_core/utils/function_calling.py#L276

Modified to allow for tool augmentations
"""

import inspect
import re
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    get_args,
    get_origin,
)

from langchain_core.pydantic_v1 import BaseModel

from tool_sandbox.common.execution_context import (
    TOOL_AUGMENTATION_TYPE,
    ScenarioCategories,
    get_current_context,
)
from tool_sandbox.common.utils import NotGiven


def default_parameter_processing(
    params: list[inspect.Parameter],
) -> list[inspect.Parameter]:
    """Modify the function arg spec of tool to a format more friendly for convert_to_openai_tool.
    In specific

    1. Remove Optional
    2. Remove NotGiven from Union types

    Args:
        params:   params to be processed

    Returns:
        Modified tool params
    """
    processed_params = []
    # Iterate through annotations. Note that this only unpacks top level annotation. Doesn't do so recursively
    for param in params:
        parameter_type = param.annotation
        type_origin = get_origin(parameter_type)
        type_args = get_args(parameter_type)

        # The OpenAI API function format does not support union or optional types. So if
        # possible we simplify those types below.
        if type_origin != Union:
            processed_params.append(param)
            continue

        # For an `Optional[str]`, `type_origin`` will be `Union` and `type_args`` will
        # be `(str, None)`. In that case, remove the `None` or `NotGiven` from the union
        # and extract the plain type.
        real_types = [t for t in type_args if t not in (type(None), NotGiven)]
        if len(real_types) == 1:
            param = param.replace(annotation=type_args[0])
        elif all(type in (int, float) for type in type_args):
            # Special case: `Union[int, float]` can be represented as float based on
            # PEP-0484:
            #   "when an argument is annotated as having type float, an argument of type
            #   int is acceptable"
            # , see https://peps.python.org/pep-0484/#the-numeric-tower .
            param = param.replace(annotation=float)

        processed_params.append(param)

    return processed_params


def maybe_scramble_arg_type(
    params: list[inspect.Parameter],
    tool_augmentation_list: list[TOOL_AUGMENTATION_TYPE],
) -> list[inspect.Parameter]:
    """Modify the function arg spec of tool by removing arg types

    Args:
        params:                   params to be processed
        tool_augmentation_list:   The list of augmentations we wish to apply

    Returns:
        Modified tool params
    """
    scramble = ScenarioCategories.ARG_TYPE_SCRAMBLED in tool_augmentation_list
    return [
        parameter.replace(annotation=type(None)) if scramble else parameter
        for parameter in params
    ]


def maybe_scramble_arg_type_from_context(
    params: list[inspect.Parameter],
) -> list[inspect.Parameter]:
    """Modify the function arg spec of tool by removing arg types

    Args:
        params: params to be processed

    Returns:
        Modified tool params
    """
    return maybe_scramble_arg_type(
        params=params,
        tool_augmentation_list=get_current_context().tool_augmentation_list,
    )


def maybe_scramble_tool_description(
    docstring: str, tool_augmentation_list: list[TOOL_AUGMENTATION_TYPE]
) -> str:
    """Modify the docstring tool by removing its description in docstring

    Args:
        docstring:                  Docstring to be processed
        tool_augmentation_list:     The list of augmentations we wish to apply

    Returns:
        Modified docstring
    """

    if (
        ScenarioCategories.TOOL_DESCRIPTION_SCRAMBLED in tool_augmentation_list
        and docstring
    ):
        # Find description and replace with empty string, using this function's docstring as an example, this will
        # produce:

        # Args:
        #     docstring:                  Docstring to be processed
        #     tool_augmentation_list:     The list of augmentations we wish to apply
        # Returns:
        #      Modified docstring

        docstring = re.sub(r"^.*(?=Args:.*$)", "", docstring, flags=re.DOTALL)
    return docstring


def maybe_scramble_tool_description_from_context(docstring: str) -> str:
    """Modify the docstring tool by removing its description in docstring

    Args:
        docstring:  Docstring to be processed

    Returns:
        Modified docstring
    """
    return maybe_scramble_tool_description(
        docstring=docstring,
        tool_augmentation_list=get_current_context().tool_augmentation_list,
    )


def maybe_scramble_arg_description(
    docstring: str, tool_augmentation_list: list[TOOL_AUGMENTATION_TYPE]
) -> str:
    """Modify the docstring tool by removing its argument descriptions in docstring

    Args:
        docstring:                  Docstring to be processed
        tool_augmentation_list:     The list of augmentations we wish to apply


    Returns:
        Modified docstring
    """
    if ScenarioCategories.ARG_DESCRIPTION_SCRAMBLED in tool_augmentation_list:
        if docstring:
            # Find description and replace with empty string, using this function's docstring as an example, this will
            # produce:

            # Modify the docstring tool by removing its argument descriptions in docstring
            #
            # Args:
            #
            # Returns:
            #      Modified docstring

            docstring = re.sub(
                r"(?<=Args:\n)(.*?)(?=\nReturns)", "", docstring, flags=re.DOTALL
            )
    return docstring


def maybe_scramble_arg_description_from_context(docstring: str) -> str:
    """Modify the docstring tool by removing its argument descriptions in docstring

    Args:
        docstring:  Docstring to be processed

    Returns:
        Modified docstring
    """
    return maybe_scramble_arg_description(
        docstring=docstring,
        tool_augmentation_list=get_current_context().tool_augmentation_list,
    )


def augmented_getdoc(tool: Callable[..., Any]) -> Optional[str]:
    """Extract doc string from tool with tool augmentation

    Args:
        tool:   Tool to extract docstring from

    Returns:
        Extracted docstring
    """
    docstring: Optional[str] = inspect.getdoc(tool)
    if docstring is None:
        return docstring
    docstring = maybe_scramble_tool_description_from_context(docstring)
    docstring = maybe_scramble_arg_description_from_context(docstring)
    return docstring


def augmented_parameters(tool: Callable[..., Any]) -> list[inspect.Parameter]:
    """Extract parameters from tool with tool augmentation

    Args:
        tool:   Tool to extract parameters from

    Returns:
        Extracted parameters
    """
    params = list(inspect.signature(tool).parameters.values())
    params = default_parameter_processing(params)
    params = maybe_scramble_arg_type_from_context(params)
    return params


PYTHON_TO_JSON_TYPES = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}


def _get_python_function_name(function: Callable[..., Any]) -> str:
    """Get the name of a Python function."""
    return function.__name__


def _parse_python_function_docstring(
    function: Callable[..., Any],
) -> Tuple[str, dict[str, str]]:
    """Parse the function and argument descriptions from the docstring of a function.

    Assumes the function docstring follows Google Python style guide.
    """
    docstring = augmented_getdoc(function)
    if docstring:
        docstring_blocks = docstring.split("\n\n")
        descriptors = []
        args_block = None
        past_descriptors = False
        for block in docstring_blocks:
            if block.startswith("Args:"):
                args_block = block
                break
            elif block.startswith("Returns:") or block.startswith("Example:"):
                # Don't break in case Args come after
                past_descriptors = True
            elif not past_descriptors:
                descriptors.append(block)
            else:
                continue
        description = " ".join(descriptors)
    else:
        description = ""
        args_block = None
    arg_descriptions = {}
    if args_block:
        arg = None
        for line in args_block.split("\n")[1:]:
            if ":" in line:
                arg, desc = line.split(":", maxsplit=1)
                arg_descriptions[arg.strip()] = desc.strip()
            elif arg:
                arg_descriptions[arg.strip()] += " " + line.strip()
    return description, arg_descriptions


def _get_python_function_arguments(
    function: Callable[..., Any], arg_descriptions: dict[str, str]
) -> dict[str, Any]:
    """Get JsonSchema describing a Python functions arguments.

    Assumes all function arguments are of primitive types (int, float, str, bool) or
    are subclasses of pydantic.BaseModel.
    """
    properties = {}
    parameters = augmented_parameters(function)
    for param in parameters:
        arg = param.name
        arg_type = param.annotation
        if arg == "return":
            continue
        if isinstance(arg_type, type) and issubclass(arg_type, BaseModel):
            # Mypy error:
            # "type" has no attribute "schema"
            properties[arg] = arg_type.schema()
        elif (
            hasattr(arg_type, "__name__")
            and getattr(arg_type, "__name__") in PYTHON_TO_JSON_TYPES
        ):
            properties[arg] = {"type": PYTHON_TO_JSON_TYPES[arg_type.__name__]}
        elif (
            hasattr(arg_type, "__dict__")
            and getattr(arg_type, "__dict__").get("__origin__", None) == Literal
        ):
            properties[arg] = {
                "enum": list(arg_type.__args__),
                "type": PYTHON_TO_JSON_TYPES[arg_type.__args__[0].__class__.__name__],
            }
        # Note that we cannot raise the `RuntimeError` below since this is the expected
        # behavior when arg type scrambling is enabled.
        # else:
        #     raise RuntimeError(
        #         f"Parameter with name '{arg}' of type '{arg_type}' is not being "
        #         f"handled.\n{function=}\n{arg_descriptions=}"
        #     )
        if arg in arg_descriptions:
            if arg not in properties:
                properties[arg] = {}
            properties[arg]["description"] = arg_descriptions[arg]
    return properties


def _get_python_function_required_args(function: Callable[..., Any]) -> List[str]:
    """Get the required arguments for a Python function."""
    params = augmented_parameters(function)
    required = [p.name for p in params if p.default == p.empty]
    is_class = type(function) is type
    if is_class and required[0] == "self":
        required = required[1:]
    return required


def convert_python_function_to_openai_function(
    name: str,
    function: Callable[..., Any],
) -> Dict[str, Any]:
    """Convert a Python function to an OpenAI function-calling API compatible dict.

    Assumes the Python function has type hints and a docstring with a description. If
    the docstring has Google Python style argument descriptions, these will be included
    as well.

    Args:
        name:      The tool name. This is not necessarily the same as
                   `function.__name__` as the tool names can be scrambled, but the
                   execution environment uses the original tool names.
        function:  A Python function.

    Returns:
        An OpenAI compatible function declaration object.
    """
    description, arg_descriptions = _parse_python_function_docstring(function)
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": _get_python_function_arguments(function, arg_descriptions),
            "required": _get_python_function_required_args(function),
        },
    }


def convert_to_openai_tool(
    tool: Callable[..., Any],
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Convert a raw function/class to an OpenAI tool.

    Args:
        tool:  A Python function.
        name:  The tool name. This is not necessarily the same as `function.__name__` as
               the tool names can be scrambled, but the execution environment uses the
               original tool names.

    Returns:
        A dict version of the passed in tool which is compatible with the OpenAI
        tool-calling API.
    """
    name = _get_python_function_name(tool) if name is None else name
    function = convert_python_function_to_openai_function(name, tool)
    return {"type": "function", "function": function}


def convert_to_openai_tools(
    name_to_tool: dict[str, Callable[..., Any]],
) -> list[dict[str, Any]]:
    return [convert_to_openai_tool(tool, name) for name, tool in name_to_tool.items()]
