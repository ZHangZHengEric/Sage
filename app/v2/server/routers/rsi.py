"""Owner-scoped RSI operations; HTTP disconnection never cancels an experiment."""

from fastapi import APIRouter, Query

from app.v2.server.optimization.contracts import RsiApply, RsiStart
from app.v2.server.routers.deps import CurrentUser, HostDep, ReadUser
from app.v2.server.routers.packages import result

router = APIRouter(prefix="/api/agents/{agent_id}/rsi", tags=["rsi"])


@router.post("/runs")
async def start(agent_id: str, body: RsiStart, user: CurrentUser, host: HostDep):
    return await result(host.rsi.start(user.user_id, agent_id, body))


@router.get("/runs")
async def history(agent_id: str, user: ReadUser, host: HostDep,
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return await result(host.rsi.list(user.user_id, agent_id, limit=limit, offset=offset))


@router.get("/runs/{run_id}")
async def status(agent_id: str, run_id: str, user: ReadUser, host: HostDep):
    return await result(host.rsi.get(user.user_id, agent_id, run_id))


@router.post("/runs/{run_id}/cancel")
async def cancel(agent_id: str, run_id: str, user: CurrentUser, host: HostDep):
    return await result(host.rsi.cancel(user.user_id, agent_id, run_id))


@router.post("/runs/{run_id}/resume")
async def resume(agent_id: str, run_id: str, user: CurrentUser, host: HostDep):
    return await result(host.rsi.resume(user.user_id, agent_id, run_id))


@router.get("/runs/{run_id}/versions/{version_id}")
async def version(agent_id: str, run_id: str, version_id: str, user: ReadUser, host: HostDep):
    return await result(host.rsi.version(user.user_id, agent_id, run_id, version_id))


@router.post("/runs/{run_id}/versions/{version_id}/apply")
async def apply(agent_id: str, run_id: str, version_id: str, body: RsiApply, user: CurrentUser, host: HostDep):
    return await result(host.rsi.apply(user.user_id, agent_id, run_id, version_id, body.expected_package_ref))
