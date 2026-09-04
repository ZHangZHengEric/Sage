from fastapi import APIRouter, File, UploadFile

from app.server_v2.api.deps import CurrentUser, ServiceDep
from app.server_v2.core.errors import ServerV2Error, success
from app.server_v2.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.schemas.http import (
    SkillBindBody,
    SkillPublic,
    SkillPublishBody,
    SkillUpdateBody,
    SkillUploadResult,
    WorkspaceSkillBody,
)

router = APIRouter(tags=["skills"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/skills", response_model=ApiResponse[list[SkillPublic]])
async def list_skills(user: CurrentUser, service: ServiceDep):
    skills = await service.skill_catalog.list_visible(user_id=user.user_id, role=user.role)
    return success([item.public_dict() for item in skills])


@router.post("/api/skills/upload", response_model=ApiResponse[SkillUploadResult])
async def upload_skills(
    user: CurrentUser,
    service: ServiceDep,
    files: list[UploadFile] = File(...),
):
    if not files:
        raise ServerV2Error("validation", "select at least one zip")
    payloads: list[tuple[str, bytes]] = []
    for item in files:
        filename = item.filename or "unknown.zip"
        if not filename.lower().endswith(".zip"):
            payloads.append((filename, b""))
            continue
        payloads.append((filename, await item.read()))
    return success(
        await service.skill_catalog.publish_zips(
            payloads, user_id=user.user_id, role=user.role
        )
    )


@router.post("/api/skills", response_model=ApiResponse[SkillPublic])
async def publish_skill(body: SkillPublishBody, user: CurrentUser, service: ServiceDep):
    record = await service.skill_catalog.publish_markdown(
        name=body.name,
        content=body.content,
        user_id=user.user_id,
        role=user.role,
        dimension=body.dimension,
    )
    return success(record.public_dict())


@router.get("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def get_skill(skill_id: str, user: CurrentUser, service: ServiceDep):
    record = await service.skill_catalog.get(skill_id, user_id=user.user_id, role=user.role)
    payload = record.public_dict()
    payload["content"] = await service.skill_catalog.read_content(
        skill_id, user_id=user.user_id, role=user.role
    )
    return success(payload)


@router.put("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def update_skill(
    skill_id: str, body: SkillUpdateBody, user: CurrentUser, service: ServiceDep
):
    record = await service.skill_catalog.update_content(
        skill_id, body.content, user_id=user.user_id, role=user.role
    )
    return success(record.public_dict())


@router.delete("/api/skills/{skill_id}", response_model=ApiResponse[None])
async def delete_skill(skill_id: str, user: CurrentUser, service: ServiceDep):
    await service.skill_catalog.disable(skill_id, user_id=user.user_id, role=user.role)
    return success()


@router.get("/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]])
async def list_agent_skills(agent_id: str, user: CurrentUser, service: ServiceDep):
    skills = await service.skill_catalog.bound_skills(
        owner_user_id=user.user_id, agent_id=agent_id
    )
    return success(
        [
            {
                **item.public_dict(),
                "workspace_status": await service.skill_catalog.workspace_status(
                    user_id=user.user_id, name=item.name
                ),
            }
            for item in skills
        ]
    )


@router.put("/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]])
async def bind_agent_skills(
    agent_id: str, body: SkillBindBody, user: CurrentUser, service: ServiceDep
):
    catalog = await service.catalog.get(user.user_id)
    skills = await service.skill_catalog.bind_agent_skills(
        owner_user_id=user.user_id,
        agent_id=agent_id,
        names=body.names,
        catalog=catalog,
    )
    await service.catalog.save(user.user_id, catalog)
    return success([item.public_dict() for item in skills])


@router.put(
    "/api/workspace/skills/{name}",
    response_model=ApiResponse[dict],
)
async def write_workspace_skill(
    name: str, body: WorkspaceSkillBody, user: CurrentUser, service: ServiceDep
):
    path = await service.skill_catalog.write_workspace_skill(
        user_id=user.user_id, name=name, content=body.content
    )
    return success(
        {
            "name": name,
            "workspace_path": str(path),
            "status": await service.skill_catalog.workspace_status(
                user_id=user.user_id, name=name
            ),
        }
    )
