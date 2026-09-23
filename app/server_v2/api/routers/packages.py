"""HTTP and model tools share AgentManagementService semantics and authorization."""

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.errors import SageV2Error
from app.server_v2.api.deps import AdminUser, CurrentUser, PackageDep
from app.server_v2.core.errors import ServerV2Error, map_sage_error, success

router = APIRouter(prefix="/api/agent-packages", tags=["agent-packages"])


async def result(operation):
    try:
        return success(await operation)
    except PermissionError as exc:
        raise ServerV2Error("forbidden", str(exc)) from exc
    except ValueError as exc:
        reason = (
            "rate_limited"
            if "capacity reached" in str(exc)
            else "not_found"
            if "not found" in str(exc)
            else "conflict"
            if (
                "conflict" in str(exc)
                or "immutable" in str(exc)
                or "reused" in str(exc)
            )
            else "validation"
        )
        raise ServerV2Error(reason, str(exc)) from exc
    except SyntaxError as exc:
        raise ServerV2Error("validation", f"plugin syntax error at line {exc.lineno}: {exc.msg}") from exc
    except SageV2Error as exc:
        raise map_sage_error(exc) from exc


class Validation(BaseModel):
    bundle: AgentPackageBundle
    readiness: bool = False


class Activation(BaseModel):
    expected_ref: str | None = None


class Fork(BaseModel):
    package_id: str
    version: str


class Invocation(BaseModel):
    ref: str
    agent_id: str
    content: str = Field(min_length=1)
    operation: str = Field(min_length=1, max_length=200)
    session_id: str | None = None


class Control(BaseModel):
    action: Literal["cancel", "reply", "approve"]
    decision: str = ""
    interaction_id: str | None = None
    payload: dict | None = None


@router.get("/schema")
async def schema(user: CurrentUser, packages: PackageDep):
    return success(packages.schema())


@router.get("/capacity")
async def capacity(user: AdminUser, packages: PackageDep):
    return success(packages.capacity_snapshot())


@router.get("/resources")
async def resources(user: CurrentUser, packages: PackageDep):
    return await result(
        packages.resources(packages.context_for(user.user_id))
    )


@router.get("/template")
async def template(user: CurrentUser, packages: PackageDep, agent_id: str | None = None):
    return await result(
        packages.template(
            packages.context_for(user.user_id), agent_id
        )
    )


@router.get("")
async def inventory(
    user: CurrentUser,
    packages: PackageDep,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await result(
        packages.list(
            packages.context_for(user.user_id), limit=limit, offset=offset
        )
    )


@router.post("/validate")
async def validate(body: Validation, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.validate(
            body.bundle, packages.context_for(user.user_id), readiness=body.readiness
        )
    )


@router.post("")
async def save(body: AgentPackageBundle, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.save(body, packages.context_for(user.user_id))
    )


@router.get("/runs")
async def runs(
    user: CurrentUser,
    packages: PackageDep,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await result(
        packages.list_runs(
            packages.context_for(user.user_id), limit=limit, offset=offset
        )
    )


@router.post("/runs")
async def run(body: Invocation, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.run(
            body.ref,
            body.agent_id,
            body.content,
            body.operation,
            packages.context_for(user.user_id),
            session_id=body.session_id,
        )
    )


@router.get("/runs/{operation}")
async def status(operation: str, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.status(
            operation, packages.context_for(user.user_id)
        )
    )


@router.get("/runs/{operation}/events")
async def events(
    operation: str,
    user: CurrentUser,
    packages: PackageDep,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=200),
):
    return await result(
        packages.events(
            operation,
            packages.context_for(user.user_id),
            after_sequence=after_sequence,
            limit=limit,
        )
    )


@router.post("/runs/{operation}/control")
async def control(
    operation: str, body: Control, user: CurrentUser, packages: PackageDep
):
    return await result(
        packages.control(
            operation,
            "reply" if body.action == "approve" else body.action,
            packages.context_for(user.user_id),
            decision=body.decision,
            interaction_id=body.interaction_id,
            payload=body.payload,
            allow_privileged_interaction=body.action == "approve",
        )
    )


@router.get("/{ref}")
async def get(ref: str, user: CurrentUser, packages: PackageDep):
    async def read():
        return (
            await packages.get(
                ref, packages.context_for(user.user_id)
            )
        ).model_dump(mode="json")

    return await result(read())


@router.post("/{ref}/activate")
async def activate(ref: str, body: Activation, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.activate(
            ref, body.expected_ref, packages.context_for(user.user_id)
        )
    )


@router.post("/{ref}/fork")
async def fork(ref: str, body: Fork, user: CurrentUser, packages: PackageDep):
    return await result(
        packages.fork(
            ref, body.package_id, body.version, packages.context_for(user.user_id)
        )
    )
