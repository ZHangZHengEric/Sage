# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""WARNING: This is not thread safe! For thread safety we'll need to implement something similar to
axlearn's InvocationContext
https://github.com/apple/axlearn/blob/c84f50e6cba467ce5c2096d0cba3dce4c73f897a/axlearn/common/module.py#L140-L153

We are effectively implementing Singleton OOP behavior in procedural programming paradigm,
which will look weird and unsafe for sure. Better encapsulation ideas are greatly appreciated!
"""

from __future__ import annotations

import bisect
import code
import contextlib
import copy
import uuid
from enum import auto
from logging import getLogger
from typing import Any, Callable, Iterator, Literal, Optional, cast

import dill  # type: ignore[import-untyped]
import polars as pl
from polars.exceptions import NoDataError
from polars.type_aliases import IntoExprColumn
from strenum import StrEnum

from tool_sandbox.common.tool_discovery import (
    ToolBackend,
    get_all_tools,
    get_scrambled_tool_names,
)


class DatabaseNamespace(StrEnum):
    """Namespace for each database"""

    SANDBOX = auto()
    SETTING = auto()
    CONTACT = auto()
    MESSAGING = auto()
    REMINDER = auto()


class RoleType(StrEnum):
    """Types of roles available in the sandbox"""

    SYSTEM = auto()
    USER = auto()
    AGENT = auto()
    EXECUTION_ENVIRONMENT = auto()


class ScenarioCategories(StrEnum):
    """Categorical enum describing scenarios. Each scenario can belong to multiple categories"""

    # Scenario that requires a single tool call to complete
    SINGLE_TOOL_CALL = auto()
    # Scenario that requires a multiple tool call to complete
    MULTIPLE_TOOL_CALL = auto()
    # Scenario that requires a single user turn to complete. Note that this doesn't mean
    # there has to be only 1 user turn in the trajectory. If the agent attempted to look for help
    # from the user, there could be multiple user turns in the rollout
    SINGLE_USER_TURN = auto()
    # Scenario that requires a multiple user turn to complete.
    MULTIPLE_USER_TURN = auto()
    # Scenario that involves tools that depends on certain expected world state, and raises error if the expectation
    # is not met
    STATE_DEPENDENCY = auto()
    # Scenario that requires surface form text to be transformed into canonical form
    CANONICALIZATION = auto()
    # Scenario that requires co-reference resolution
    COREFERENCE = auto()
    # Scenario that requires disambiguation between multiple entities / tool choices
    DISAMBIGUATION = auto()
    # Scenario that cannot be completed with the provided tools / user prompts
    INSUFFICIENT_INFORMATION = auto()
    # Tool augmentations
    # All tools provided are necessary to complete the scenario
    NO_DISTRACTION_TOOLS = auto()
    # 3 distraction tools provided in addition to necessary ones
    THREE_DISTRACTION_TOOLS = auto()
    # 10 distraction tools provided in addition to necessary ones
    TEN_DISTRACTION_TOOLS = auto()
    # All tools in the sandbox provided
    ALL_TOOLS_AVAILABLE = auto()
    # Tool names are replaced with less descriptive generic names,
    # E.g. messaging_1 instead of send_message_with_phone_number
    TOOL_NAME_SCRAMBLED = auto()
    # Tool descriptions are removed
    TOOL_DESCRIPTION_SCRAMBLED = auto()
    # Argument description are removed
    ARG_DESCRIPTION_SCRAMBLED = auto()
    # Argument names are replaced with less descriptive generic names,
    # E.g. arg_1 instead of phone_number
    ARG_NAME_SCRAMBLED = auto()
    # Argument type annotations are removed
    ARG_TYPE_SCRAMBLED = auto()


TOOL_AUGMENTATION_TYPE = Literal[
    ScenarioCategories.TOOL_NAME_SCRAMBLED,
    ScenarioCategories.TOOL_DESCRIPTION_SCRAMBLED,
    ScenarioCategories.ARG_DESCRIPTION_SCRAMBLED,
    ScenarioCategories.ARG_TYPE_SCRAMBLED,
    ScenarioCategories.ARG_NAME_SCRAMBLED,
]


LOGGER = getLogger(__name__)


class ExecutionContext:
    """Execution Context for sandbox simulation.

    Each ExecutionContext object is a full encapsulation of the sandbox world state, which

    1. Contains database for multiple tools which enables stateful execution
    without listing world state as function arguments.
    2. Contains database for messages, capturing conversation between different roles
    3. Contains an InteractiveConsole object used to execute code snippets coming from the agent

    All database contains a full history of how the database changed across time. Time is indexed by a column
    "sandbox_message_index", which connects other databases with Agent database. When a state database change happened,
    a snapshot of the most recent database state is created. The new snapshot is linked to the message causing the
    change, so that we can recover at any given point what the world state is without unnecessary duplication.

    All database also contains a null row as "headguard", making sure we can represent an empty snapshot

    One should instantiate this class as a global variable
    for all tools to access without taking ExecutionContext as function argument
    """

    # Database schema. Declared as class attributes so that it could be available prior to init
    # As you add more databases / columns, remember to also add their default similarity measure to
    # tool_sandbox.common.evaluation._default_dbs_column_similarities
    dbs_schemas: dict[DatabaseNamespace, dict[str, Any]] = {
        DatabaseNamespace.SANDBOX: {
            "sandbox_message_index": pl.Int32,
            "sender": pl.Enum([x for x in RoleType]),
            "recipient": pl.Enum([x for x in RoleType]),
            "content": pl.String,
            "openai_tool_call_id": pl.String,
            "openai_function_name": pl.String,
            "conversation_active": pl.Boolean,
            "tool_call_exception": pl.String,
            "tool_trace": pl.List(pl.String),
            "visible_to": pl.List(pl.Enum([x for x in RoleType])),
        },
        DatabaseNamespace.SETTING: {
            "sandbox_message_index": pl.Int32,
            "device_id": pl.String,
            "cellular": pl.Boolean,
            "wifi": pl.Boolean,
            "location_service": pl.Boolean,
            "low_battery_mode": pl.Boolean,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
        },
        DatabaseNamespace.CONTACT: {
            "sandbox_message_index": pl.Int32,
            "person_id": pl.String,
            "name": pl.String,
            "phone_number": pl.String,
            "relationship": pl.String,
            "is_self": pl.Boolean,
        },
        DatabaseNamespace.MESSAGING: {
            "sandbox_message_index": pl.Int32,
            "message_id": pl.String,
            "sender_person_id": pl.String,
            "sender_phone_number": pl.String,
            "recipient_person_id": pl.String,
            "recipient_phone_number": pl.String,
            "content": pl.String,
            "creation_timestamp": pl.Float64,
        },
        DatabaseNamespace.REMINDER: {
            "sandbox_message_index": pl.Int32,
            "reminder_id": pl.String,
            "content": pl.String,
            "creation_timestamp": pl.Float64,
            "reminder_timestamp": pl.Float64,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
        },
    }

    def __init__(
        self,
        tool_allow_list: Optional[list[str]] = None,
        tool_deny_list: Optional[list[str]] = None,
        tool_augmentation_list: Optional[list[TOOL_AUGMENTATION_TYPE]] = None,
        preferred_tool_backend: ToolBackend = ToolBackend.DEFAULT,
    ):
        """Init function for ExecutionContext

        Args:
            tool_allow_list:            Override the default init values for self.tool_allow_list.
            tool_deny_list:             Override the default init values for self.tool_deny_list.
            tool_augmentation_list:     Possible tool augmentations we wish to apply.
            preferred_tool_backend:     Choose the backend over others when conflicting tool names were found.
        """
        # Each database starts with a full null headguard except on "sandbox_message_index" column, which is set to 0.
        self._dbs: dict[str, pl.DataFrame] = {
            namespace: pl.DataFrame(
                {
                    k: None if k != "sandbox_message_index" else 0
                    for k in self.dbs_schemas[namespace]
                },
                schema=self.dbs_schemas[namespace],
            )
            for namespace in self.dbs_schemas
        }
        # Add default settings database state
        self._dbs[DatabaseNamespace.SETTING] = self._dbs[
            DatabaseNamespace.SETTING
        ].vstack(
            pl.DataFrame(
                {
                    "sandbox_message_index": 0,
                    "device_id": str(
                        uuid.uuid5(namespace=uuid.NAMESPACE_URL, name="my_phone")
                    ),
                    "cellular": True,
                    "wifi": True,
                    "location_service": True,
                    "low_battery_mode": False,
                    "latitude": 37.334606,
                    "longitude": -122.009102,
                },
                schema=self.dbs_schemas[DatabaseNamespace.SETTING],
            )
        )
        self.interactive_console = code.InteractiveConsole()
        # If is None, allow all tools, otherwise only allow tools with these names to be accessed by the Agent
        self.tool_allow_list: Optional[list[str]] = tool_allow_list
        # If is None, deny no tools, otherwise any tool name present in this list cannot be accessed by the Agent
        self.tool_deny_list: Optional[list[str]] = tool_deny_list
        # Config for "tracing" tools. If True, input and output to tools will be saved in Sandbox database alongside
        # corresponding message
        self.trace_tool: bool = False
        # Possible tool augmentations
        self.tool_augmentation_list: list[TOOL_AUGMENTATION_TYPE] = (
            [] if tool_augmentation_list is None else tool_augmentation_list
        )
        # Choose the following backend over others, if conflicting tool names were found.
        self.preferred_tool_backend = preferred_tool_backend

        self.name_to_tool = get_all_tools(self.preferred_tool_backend)
        # Compute the scrambled tool names.
        self._actual_to_scrambled_tool_name = get_scrambled_tool_names(
            self.name_to_tool.values()
        )
        # If multiple tools had the same function name then the dictionary would have
        # fewer elements. Unique tool names are already enforced in
        # `find_tools_by_module`, but just to be defensive we assert that here as well.
        assert len(self.name_to_tool) == len(self._actual_to_scrambled_tool_name)
        self._scrambled_to_actual_tool_name = {
            v: k for k, v in self._actual_to_scrambled_tool_name.items()
        }
        # Consistency check since theoretically multiple tools could have the same
        # scrambled name meaning that entries in `scrambled_to_actual_tool_name` would
        # be overwritten.
        assert len(self._actual_to_scrambled_tool_name) == len(
            self._scrambled_to_actual_tool_name
        )

    def get_agent_facing_tool_name(self, tool_name: str) -> str:
        """Get the agent facing tool name.

        Args:
            tool_name:  The (execution facing) name of the tool.

        Returns:
            The agent facing tool name. More specifically, a scrambled tool name if tool
            name scrambling is enabled. Otherwise `tool_name` is returned unmodified.
        """
        return (
            self._actual_to_scrambled_tool_name[tool_name]
            if ScenarioCategories.TOOL_NAME_SCRAMBLED in self.tool_augmentation_list
            else tool_name
        )

    def get_agent_to_execution_facing_tool_name(self) -> dict[str, str]:
        """Get the mapping from agent to execution facing tool name."""
        if ScenarioCategories.TOOL_NAME_SCRAMBLED in self.tool_augmentation_list:
            return self._scrambled_to_actual_tool_name
        return {name: name for name in self.name_to_tool}

    def get_execution_facing_tool_name(self, agent_facing_tool_name: str) -> str:
        """Get the execution facing tool name.

        Args:
            agent_facing_tool_name:  The (agent facing) name of the tool.

        Returns:
            The execution facing tool name. More specifically, an unscrambled tool name
            if tool name scrambling is enabled. Otherwise `agent_facing_tool_name` is
            returned unmodified.
        """
        return (
            self._scrambled_to_actual_tool_name[agent_facing_tool_name]
            if ScenarioCategories.TOOL_NAME_SCRAMBLED in self.tool_augmentation_list
            else agent_facing_tool_name
        )

    def get_available_tools(
        self,
        scrambling_allowed: bool,
    ) -> dict[str, Callable[..., Any]]:
        """Get the tools that are allowed to be used.

        Args:
            scrambling_allowed:  Flag to decide if tool scrambling is allowed. This is
                                 used by the user agent role to avoid scrambling the
                                 end conversation tool.

        Note: This is a function instead of pre-computed in the constructor since the
        scenario extensions may modify the tool allow and deny lists and then the
        pre-computed allowed tools would be out of sync.

        Note: The key of the dictionary is the agent facing tool name while the function
        object itself stores the execution facing tool name (accessible as `__name__`).
        The agent and execution facing tool names are identical when tool name
        scrambling is disabled.
        """
        name_to_tool = {
            name: tool
            for name, tool in self.name_to_tool.items()
            if (self.tool_allow_list is None or name in self.tool_allow_list)
            and (self.tool_deny_list is None or name not in self.tool_deny_list)
        }
        if (
            not scrambling_allowed
            or ScenarioCategories.TOOL_NAME_SCRAMBLED not in self.tool_augmentation_list
        ):
            return name_to_tool

        return {
            self.get_agent_facing_tool_name(name): tool
            for name, tool in name_to_tool.items()
        }

    def to_dict(self, serialize_console: bool = True) -> dict[str, Any]:
        """Serializes to a dictionary

        We aim to make this serialization reversible, while still somewhat readable.

        Args:
            serialize_console:  If true, serialize interactive_console with dill. Note that this
                                cannot be dumped with json

        Returns:
            A serialized dict.
        """
        return {
            "_dbs": {
                namespace: database.to_dicts()
                for namespace, database in self._dbs.items()
            },
            "interactive_console": dill.dumps(self.interactive_console)
            if serialize_console
            else None,
            "tool_allow_list": self.tool_allow_list,
            "tool_deny_list": self.tool_deny_list,
            "trace_tool": self.trace_tool,
            "tool_augmentation_list": [str(x) for x in self.tool_augmentation_list],
            "preferred_tool_backend": self.preferred_tool_backend,
        }

    @classmethod
    def from_dict(cls, serialized_dict: dict[str, Any]) -> ExecutionContext:
        """Load a serialized dict produced by to_dict.

        Args:
            serialized_dict:    Serialized dict object.

        Returns:
            ExecutionContext object.
        """
        execution_context = cls()
        # Load _dbs
        for namespace in serialized_dict["_dbs"]:
            execution_context._dbs[DatabaseNamespace[namespace]] = pl.from_dicts(
                serialized_dict["_dbs"][namespace], schema=cls.dbs_schemas[namespace]
            )
        # Load interactive_console
        execution_context.interactive_console = (
            dill.loads(serialized_dict["interactive_console"])
            if serialized_dict["interactive_console"] is not None
            else execution_context.interactive_console
        )
        # Load tool_allow_list
        execution_context.tool_allow_list = serialized_dict["tool_allow_list"]
        # Load tool_deny_list
        execution_context.tool_deny_list = serialized_dict["tool_deny_list"]
        # Load trace_tool
        execution_context.trace_tool = serialized_dict["trace_tool"]
        # Load tool_augmentation_list
        execution_context.tool_augmentation_list = [
            cast(TOOL_AUGMENTATION_TYPE, ScenarioCategories[x])
            for x in serialized_dict["tool_augmentation_list"]
        ]
        # Load preferred_tool_backend
        execution_context.preferred_tool_backend = serialized_dict[
            "preferred_tool_backend"
        ]
        return execution_context

    def __deepcopy__(self, memo: dict[int, Any]) -> ExecutionContext:
        # The `InteractiveConsole` is not copyable/picklable with the Python standard
        # library. `dill` adds support for pickling additional Python objects so it can
        # successfully copy an `InteractiveConsole`. Note that `dill.copy` performs a
        # deep copy.
        return cast(ExecutionContext, dill.copy(self))

    @staticmethod
    def headguard_predicate(column_names: set[str]) -> pl.Expr:
        """A polars expression matching headguard rows

        Specifically this looks for rows where all columns expect "sandbox_message_index" are None

        Args:
            column_names:   Column names in the dataframe
        Returns:
            A polars expression matching headguard rows
        """
        # Hacky way to make bitwise and work in a loop
        return pl.lit(True).and_(
            *[
                pl.col(column_name).is_null()
                for column_name in (column_names - {"sandbox_message_index"})
            ]
        )

    @classmethod
    def drop_headguard(cls, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Drops the all None headguard row

        Args:
            dataframe:  Dataframe to drop headguard row from. Usually a snapshot or multiple snapshots

        Returns:
            Dataframe with headguard dropped.
        """
        return dataframe.filter(
            ~cls.headguard_predicate(column_names=set(dataframe.columns))
        )

    @property
    def max_sandbox_message_index(self) -> int:
        """Get the current max_sandbox_index, returns -1 when no messages exist

        Returns:

        """
        series = self.drop_headguard(self._dbs[DatabaseNamespace.SANDBOX]).get_column(
            "sandbox_message_index"
        )
        if series.is_empty():
            return -1
        return cast(int, series.max())

    @property
    def first_user_sandbox_message_index(self) -> int:
        """Get the sandbox message index of the first user sent message.

        Skips over all user simulation few shot prompts

        Snapshot at this position defines the starting world state. returns -1 if no user message was found

        Returns:

        """
        user_messages_db: pl.DataFrame = self.get_database(
            namespace=DatabaseNamespace.SANDBOX,
            get_all_history_snapshots=True,
            drop_sandbox_message_index=False,
        ).filter(
            (pl.col("sender") == RoleType.USER)
            & (
                (pl.col("visible_to") != [RoleType.USER])
                | (pl.col("visible_to").is_null())
            )
        )
        if user_messages_db.is_empty():
            return -1
        return cast(int, user_messages_db["sandbox_message_index"][0])

    def get_most_recent_snapshot_sandbox_message_index(
        self, namespace: DatabaseNamespace, query_index: int
    ) -> int:
        """Find sandbox_message_index corresponding to the most recent snapshot no later than query_index

        Args:
            namespace:      Namespace to search under
            query_index:    Query index

        Returns:
            Target index

        Raises:
            IndexError:     When query_index is larger than the largest available sandbox_message_index in Sandbox DB
        """
        # When the database is empty, default to -1
        if self.drop_headguard(self._dbs[namespace]).is_empty():
            return -1
        snapshot_indices = (
            self._dbs[namespace].get_column("sandbox_message_index").unique()
        ).sort()
        # Maximum legal index for any database to have is max_sandbox + 1. Since database could be adding entry
        # corresponding to the current message being processed, which haven't been added to the SANDBOX database
        max_index = self.max_sandbox_message_index + 1
        if query_index > max_index:
            raise IndexError(
                f"{query_index=} is larger than the largest available "
                f"sandbox_message_index + 1 = {max_index} in Sandbox DB."
            )
        # Find most recent snapshot no later than query_index
        # If out of bounds, default to first available snapshot, which should always be 0 due to default headguard
        idx = snapshot_indices[
            max((bisect.bisect(a=snapshot_indices, x=query_index) - 1), 0)
        ]
        return cast(int, idx)

    def _maybe_create_snapshot(self, namespace: DatabaseNamespace) -> None:
        """If db snapshot under namespace that links to max_sandbox_message_index + 1 doesn't exist, create one

        Args:
            namespace:                      Namespace to create snapshot under

        Returns:

        """
        max_sandbox_message_index = self.max_sandbox_message_index
        if (
            self._dbs[namespace]
            .filter(pl.col("sandbox_message_index") == max_sandbox_message_index + 1)
            .is_empty()
        ):
            most_recent_index = self.get_most_recent_snapshot_sandbox_message_index(
                namespace, max_sandbox_message_index
            )
            most_recent_snapshot = self._dbs[namespace].filter(
                pl.col("sandbox_message_index") == most_recent_index
            )
            # Update sandbox_message_index and stack the new snapshot at the end of database
            self._dbs[namespace] = self._dbs[namespace].vstack(
                most_recent_snapshot.with_columns(
                    pl.when(pl.col("sandbox_message_index") == most_recent_index)
                    .then(max_sandbox_message_index + 1)
                    .alias("sandbox_message_index")
                )
            )

    def get_database(
        self,
        namespace: DatabaseNamespace,
        sandbox_message_index: Optional[int] = None,
        get_all_history_snapshots: bool = False,
        drop_sandbox_message_index: bool = True,
        drop_headguard: bool = True,
    ) -> pl.DataFrame:
        """Get a database given the namespace and sandbox_message_index

        By default, gets the most recent database snapshot. When sandbox_message_index is provided,
        find the most recent snapshot no later than sandbox_message_index

        When get_all_history_snapshots is True, return all snapshots <= sandbox_message_index, this is useful for
        accessing message history

        Note that the database returned is a subview of the original database. Please treat it as an immutable object
        to avoid unintended effect. Use add / remove functions to modify database if needed.

        Args:
            namespace:                  Database namespace
            sandbox_message_index:      Which message this database corresponds to
            get_all_history_snapshots:  Return all entries where snapshot index <= sandbox_message_index
            drop_sandbox_message_index: Drop the drop_sandbox_message_index column or not, defaults to True
            drop_headguard:             Drop the null headguard entry. Should only be turned off for debugging purposes

        Returns:
            Requested snapshot of database

        Raises:
            IndexError: When sandbox_message_index is larger than the largest available sandbox_message_index in
                        Sandbox DB
        """
        if sandbox_message_index is None:
            sandbox_message_index = self.max_sandbox_message_index + 1
        snapshot_target_index = self.get_most_recent_snapshot_sandbox_message_index(
            namespace, sandbox_message_index
        )
        predicate = (
            pl.col("sandbox_message_index") <= snapshot_target_index
            if get_all_history_snapshots
            else pl.col("sandbox_message_index") == snapshot_target_index
        )
        dataframe = self._dbs[namespace].filter(predicate)
        if drop_sandbox_message_index:
            dataframe = dataframe.drop("sandbox_message_index")
        if drop_headguard:
            dataframe = self.drop_headguard(dataframe)
        return dataframe

    def add_to_database(
        self,
        namespace: DatabaseNamespace,
        rows: list[dict[str, Any]],
    ) -> None:
        """Add multiple rows to a database

        If namespace != SANDBOX:

        Assumes that the operation is the outcome of a message that's being processed (because all messages
        already committed to the database are have finished execution). Which means we will create a snapshot if
        the snapshot doesn't exist, and start operating on this snapshot.

        If namespace == SANDBOX:

        Add the messages to SANDBOX table and increment index

        Args:
            namespace:                      Database namespace
            rows:                           List of rows to be added, each item should be a Dict of column and value

        Returns:

        Raises:
            KeyError:   When provided column names in rows does not match given schema
            ValueError: When entry is all None. All None is reserved for headguard

        """
        # Check if column name in rows are found in namespace schema
        rows_column_names = {x for row in rows for x in row.keys()}
        schema_column_names = set(self.dbs_schemas[namespace].keys())
        if rows_column_names - schema_column_names:
            raise KeyError(
                f"Only column names {schema_column_names} are allowed for namespace {namespace}. "
                f"Found unknown column name {rows_column_names - schema_column_names}"
            )
        # Check if values are all None in some rows
        for row in rows:
            if all(
                row[column_name] is None if column_name in row else True
                for column_name in schema_column_names - {"sandbox_message_index"}
            ):
                raise ValueError(
                    "Cannot add row with all None values. All None values are reserved for headguard"
                )
        rows = copy.deepcopy(rows)
        if namespace != DatabaseNamespace.SANDBOX:
            self._maybe_create_snapshot(namespace)
            # Add sandbox_message_index to rows
            for row in rows:
                row["sandbox_message_index"] = self.max_sandbox_message_index + 1
        else:
            # Carry over previous conversation_active if not provided and add message index
            previous_conversation_active = (
                True
                if self.get_database(DatabaseNamespace.SANDBOX).is_empty()
                else self.get_database(DatabaseNamespace.SANDBOX)[
                    "conversation_active"
                ][-1]
            )
            current_sandbox_message_index = self.max_sandbox_message_index + 1
            for row in rows:
                row["sandbox_message_index"] = current_sandbox_message_index
                if (
                    "conversation_active" not in row
                    or row["conversation_active"] is None
                ):
                    row["conversation_active"] = previous_conversation_active
                previous_conversation_active = row["conversation_active"]
                current_sandbox_message_index += 1
        self._dbs[namespace] = self._dbs[namespace].vstack(
            pl.DataFrame(rows, schema=self.dbs_schemas[namespace])
        )

    def remove_from_database(
        self,
        namespace: DatabaseNamespace,
        predicate: IntoExprColumn,
    ) -> None:
        """Remove multiple rows from a database

        Assumes that the operation is the outcome of a message that's being processed (because all messages
        already committed to the database are have finished execution). Which means we will create a snapshot if
        the snapshot doesn't exist, and start operating on this snapshot.

        Args:
            namespace:      Database namespace
            predicate:      A polars predicate that evaluates to boolean, used to identify the rows to remove

        Returns:

        Raises:
            NoDataError:            If no matching rows where found
            KeyError:               When attempting to remove entry from SANDBOX database
        """
        if namespace == DatabaseNamespace.SANDBOX:
            raise KeyError("Removal from SANDBOX database is not allowed")
        sandbox_message_index = self.max_sandbox_message_index + 1
        self._maybe_create_snapshot(namespace)
        # Add sandbox_message_index predicate
        predicate &= pl.col("sandbox_message_index") == sandbox_message_index
        if self._dbs[namespace].filter(predicate).is_empty():
            raise NoDataError(f"No db entry matching {predicate=} found")
        # Remove entries that match predicate, except for headguard
        self._dbs[namespace] = self._dbs[namespace].filter(
            ~predicate
            | self.headguard_predicate(column_names=set(self._dbs[namespace].columns))
        )

    def update_database(
        self,
        namespace: DatabaseNamespace,
        dataframe: pl.DataFrame,
    ) -> None:
        """Update the current database snapshot

        When simple add / remove is not sufficient, allows user to provide a new dataframe to replace the
        most recent snapshot. sandbox_message_index is overridden based on existing snapshot index

        Args:
            namespace:      Database namespace
            dataframe:      Dataframe to replace the existing snapshot

        Returns:

        """
        if namespace != DatabaseNamespace.SANDBOX:
            self._maybe_create_snapshot(namespace)
            sandbox_message_index = self.max_sandbox_message_index + 1
        else:
            # Sandbox database update points to the most recent message
            sandbox_message_index = self.max_sandbox_message_index
        # Add sandbox_message_index to dataframe
        dataframe = dataframe.with_columns(
            pl.lit(sandbox_message_index, dtype=pl.Int32).alias("sandbox_message_index")
        ).select(self._dbs[namespace].columns)
        # Add headguard if it's not provided already
        dataframe = pl.DataFrame(
            {
                k: None if k != "sandbox_message_index" else sandbox_message_index
                for k in self.dbs_schemas[namespace]
            },
            schema=self.dbs_schemas[namespace],
        ).vstack(self.drop_headguard(dataframe))
        # Update database
        self._dbs[namespace] = (
            self._dbs[namespace]
            .filter(pl.col("sandbox_message_index") != sandbox_message_index)
            .vstack(dataframe)
        )


def _create_global_execution_context() -> ExecutionContext:
    """Set up the global execution context.

    This is a workaround for the circular dependency between `ExecutionContext` and
    `tool_sandbox.tools`. More specifically, in the `ExecutionContext` we want to
    gather all registered tools so that we can scramble the tool names if requested. So
    inside `ExecutionContext.__init__` we gather the tools exposed in
    `tool_sandbox.tools`. Thus, we cannot just use
       _global_execution_context = ExecutionContext()
    at the module level since it would trigger the circular dependency. So what we are
    doing here is a lazily evaluated global variable following
    https://stackoverflow.com/a/54616590 .
    """
    execution_context = ExecutionContext()
    globals()["_global_execution_context"] = execution_context
    return execution_context


def get_current_context() -> ExecutionContext:
    """Getter for global execution context variable

    Returns
        global execution context object

    """
    # Just doing `global _global_execution_context` caused some tests to fail when
    # running them in parallel using pytest-xdist. The error was:
    #   NameError: name '_global_execution_context' is not defined
    # This has to do with how xdist executes the tests in different processes. As a
    # simple workaround we explicitly check if the global variable exists here and if
    # not we create it.
    global_execution_context = globals().get("_global_execution_context")
    if global_execution_context is None:
        return _create_global_execution_context()

    return cast(ExecutionContext, global_execution_context)


def set_current_context(execution_context: ExecutionContext) -> None:
    """Setter for global execution context variable

    Args:
        execution_context: new context to be applied as global execution context

    Returns:

    """
    globals()["_global_execution_context"] = execution_context


@contextlib.contextmanager
def new_context(context: ExecutionContext) -> Iterator[ExecutionContext]:
    """Handy context manager which patches _global_execution_context with context, and reverts after context exit

    Args:
        context:    Context to apply

    Returns:

    """
    original_context = get_current_context()
    try:
        set_current_context(context)
        yield context
    # Release resource even when exceptions are raised
    finally:
        # Reset original context
        set_current_context(original_context)


@contextlib.contextmanager
def new_context_with_attribute(**kwargs: Any) -> Iterator[ExecutionContext]:
    """Handy context manager which modifies _global_execution_context given new attributes listed in kwargs,
    and reverts after context exit

    Args:
        **kwargs:       Attribute name and values to override in _global_execution_context

    Returns:

    """
    original_context = get_current_context()
    # Make sure all attributes exist
    for attribute_name, value in kwargs.items():
        if not hasattr(original_context, attribute_name):
            raise AttributeError(
                f"Execution context does not contain attribute of name {attribute_name}"
            )
    # Gather original attributes
    original_attributes = {
        attribute_name: getattr(original_context, attribute_name)
        for attribute_name in kwargs
    }
    try:
        for attribute_name, value in kwargs.items():
            setattr(original_context, attribute_name, value)
        yield original_context
    # Release resource even when exceptions are raised
    finally:
        # Reset original context
        for attribute_name, value in original_attributes.items():
            setattr(original_context, attribute_name, value)
