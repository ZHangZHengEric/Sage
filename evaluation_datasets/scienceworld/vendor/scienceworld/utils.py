import re
import warnings

from scienceworld.constants import NAME2ID, ID2TASK


def infer_task(name_or_id: str) -> str:
    ''' Takes a task name or task ID and processes it to produce a uniform task format. '''

    if name_or_id in NAME2ID:
        name_or_id = NAME2ID[name_or_id]

    if name_or_id in ID2TASK:
        name_or_id = ID2TASK[name_or_id]

    # Correct typo fixed in b807f742050ba5d9e0c5483624c39834368cd34f
    name_or_id = name_or_id.replace("mendellian", "mendelian")

    # Remove prefix "task-##-" and any parentheses from task name.
    name_or_id = re.sub(r"task-(\d|a|b)+-|[()]", "", name_or_id)

    return name_or_id


def snake_case_deprecation_warning() -> None:
    message = "You are using the camel case api. This feature is deprecated. Please migrate to the snake_case api."
    formatted_message = f"\033[91m {message} \033[00m"
    warnings.warn(formatted_message, UserWarning, stacklevel=3)
