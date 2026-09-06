from fastapi import FastAPI

from app.server_v2.api.routers import (
    admin,
    agent,
    agents,
    auth,
    health,
    mcp,
    models,
    observability,
    skills,
    threads,
)


def register_routers(app: FastAPI, *, jaeger: bool = False) -> None:
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(models.router)
    app.include_router(agents.router)
    app.include_router(mcp.router)
    app.include_router(skills.router)
    app.include_router(threads.router)
    app.include_router(agent.router)
    app.include_router(admin.router)
    if jaeger:
        app.include_router(observability.router)
