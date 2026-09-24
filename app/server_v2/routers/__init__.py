from fastapi import FastAPI

from . import (
    a2a_agents,
    admin,
    agent,
    agents,
    api_keys,
    auth,
    health,
    mcp,
    models,
    observability,
    packages,
    skills,
    threads,
)

from app.server_v2.observability.logging import get_logger

_LOGGER = get_logger(__name__)


def register_routers(app: FastAPI, *, jaeger: bool = False) -> None:
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(models.router)
    app.include_router(agents.router)
    app.include_router(packages.router)
    app.include_router(mcp.router)
    app.include_router(a2a_agents.router)
    app.include_router(skills.router)
    app.include_router(threads.router)
    app.include_router(agent.router)
    app.include_router(api_keys.router)
    app.include_router(admin.router)
    _register_a2a(app)
    if jaeger:
        app.include_router(observability.router)


def _register_a2a(app: FastAPI) -> None:
    """Mount the A2A surface only when its optional dependency is installed.

    ``a2a-sdk`` is an extra because it drags in protobuf. A deployment that
    skips the extra still starts; it just does not speak A2A.
    """

    try:
        from . import a2a
    except ImportError as exc:
        _LOGGER.info(
            "server.a2a.disabled",
            "A2A disabled; install the a2a extra to enable it",
            attributes={"reason": str(exc)},
        )
        return
    app.include_router(a2a.router)
