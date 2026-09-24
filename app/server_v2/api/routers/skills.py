from fastapi import APIRouter, File, UploadFile

from app.server_v2.api.deps import CatalogDep, CurrentUser, SkillDep
from app.server_v2.core.errors import ServerError, success
from app.server_v2.api.schemas import AUTH_ERRORS, VALIDATION_ERRORS, ApiResponse
from app.server_v2.api.schemas.http import (
    SkillBindBody,
    SkillPublic,
    SkillPublishBody,
    SkillUpdateBody,
    SkillUploadResult,
    WorkspaceSkillBody,
)

router = APIRouter(tags=["skills"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.get("/api/skills", response_model=ApiResponse[list[SkillPublic]])
async def list_skills(user: CurrentUser, skills: SkillDep):
    skills = await skills.list_visible(user_id=user.user_id, role=user.role)
    return success([item.public_dict() for item in skills])


@router.post("/api/skills/upload", response_model=ApiResponse[SkillUploadResult])
async def upload_skills(
    user: CurrentUser,
    skills: SkillDep,
    files: list[UploadFile] = File(...),
):
    if not files:
        raise ServerError("validation", "select at least one zip")
    payloads: list[tuple[str, bytes]] = []
    for item in files:
        filename = item.filename or "unknown.zip"
        if not filename.lower().endswith(".zip"):
            payloads.append((filename, b""))
            continue
        payloads.append((filename, await item.read()))
    return success(
        await skills.publish_zips(
            payloads, user_id=user.user_id, role=user.role
        )
    )


@router.post("/api/skills", response_model=ApiResponse[SkillPublic])
async def publish_skill(body: SkillPublishBody, user: CurrentUser, skills: SkillDep):
    record = await skills.publish_markdown(
        name=body.name,
        content=body.content,
        user_id=user.user_id,
        role=user.role,
        dimension=body.dimension,
    )
    return success(record.public_dict())


@router.get("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def get_skill(skill_id: str, user: CurrentUser, skills: SkillDep):
    record = await skills.get(skill_id, user_id=user.user_id, role=user.role)
    payload = record.public_dict()
    payload["content"] = await skills.read_content(
        skill_id, user_id=user.user_id, role=user.role
    )
    return success(payload)


@router.put("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def update_skill(
    skill_id: str, body: SkillUpdateBody, user: CurrentUser, skills: SkillDep
):
    record = await skills.update_content(
        skill_id, body.content, user_id=user.user_id, role=user.role
    )
    return success(record.public_dict())


@router.delete("/api/skills/{skill_id}", response_model=ApiResponse[None])
async def delete_skill(skill_id: str, user: CurrentUser, skills: SkillDep):
    await skills.disable(skill_id, user_id=user.user_id, role=user.role)
    return success()


@router.get("/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]])
async def list_agent_skills(agent_id: str, user: CurrentUser, skills: SkillDep):
    bound = await skills.bound_skills(
        owner_user_id=user.user_id, agent_id=agent_id
    )
    return success(
        [
            {
                **item.public_dict(),
                "workspace_status": await skills.workspace_status(
                    user_id=user.user_id, name=item.name
                ),
            }
            for item in bound
        ]
    )


@router.put("/api/agents/{agent_id}/skills", response_model=ApiResponse[list[SkillPublic]])
async def bind_agent_skills(
    agent_id: str, body: SkillBindBody, user: CurrentUser, catalog: CatalogDep
):
    skills = await catalog.bind_agent_skills(
        user.user_id, agent_id, body.names
    )
    return success([item.public_dict() for item in skills])


@router.put(
    "/api/workspace/skills/{name}",
    response_model=ApiResponse[dict],
)
async def write_workspace_skill(
    name: str, body: WorkspaceSkillBody, user: CurrentUser, skills: SkillDep
):
    path = await skills.write_workspace_skill(
        user_id=user.user_id, name=name, content=body.content
    )
    return success(
        {
            "name": name,
            "workspace_path": str(path),
            "status": await skills.workspace_status(
                user_id=user.user_id, name=name
            ),
        }
    )
