from fastapi import APIRouter, File, Response, UploadFile, Query

from app.v2.server.routers.deps import ReadUser, CatalogDep, CurrentUser, SkillDep
from app.v2.server.routers.render import success
from app.v2.server.routers.schemas.common import (
    AUTH_ERRORS,
    VALIDATION_ERRORS,
    ApiResponse,
)
from app.v2.server.routers.schemas.skills import (
    SkillFilePublic,
    SkillImportBody,
    SkillImportPreview,
    SkillImportSource,
    SkillPublic,
    SkillPublishBody,
    SkillUpdateBody,
    SkillUploadResult,
    WorkspaceSkillBody,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from app.v2.server.skills.imports import SkillImportService

router = APIRouter(tags=["skills"], responses={**AUTH_ERRORS, **VALIDATION_ERRORS})


@router.post("/api/skill-import-previews", response_model=ApiResponse[SkillImportPreview])
async def preview_skill_import(body: SkillImportSource, user: CurrentUser, service: SkillDep):
    return success(await SkillImportService(service).preview(body, user_id=user.user_id))


@router.post("/api/skill-imports", response_model=ApiResponse[SkillUploadResult])
async def import_skills(body: SkillImportBody, user: CurrentUser, service: SkillDep):
    return success(await SkillImportService(service).publish(body, user_id=user.user_id))


@router.get("/api/skills", response_model=ApiResponse[list[SkillPublic]])
async def list_skills(user: ReadUser, service: SkillDep):
    skills = await service.list_visible(
        user_id=user.user_id, role=user.role
    )
    return success([item.public_dict() for item in skills])


@router.post("/api/skills/upload", response_model=ApiResponse[SkillUploadResult])
async def upload_skills(
    user: CurrentUser,
    service: SkillDep,
    files: list[UploadFile] = File(...),
):
    if not files:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.routers.skills.validation",
                category=ErrorCategory.VALIDATION,
                message="select at least one zip",
            )
        )
    payloads: list[tuple[str, bytes]] = []
    for item in files:
        filename = item.filename or "unknown.zip"
        if not filename.lower().endswith(".zip"):
            payloads.append((filename, b""))
            continue
        payloads.append((filename, await item.read()))
    return success(
        await service.publish_zips(
            payloads, user_id=user.user_id, role=user.role
        )
    )


@router.post("/api/skills", response_model=ApiResponse[SkillPublic])
async def publish_skill(body: SkillPublishBody, user: CurrentUser, service: SkillDep):
    record = await service.publish_markdown(
        name=body.name,
        content=body.content,
        user_id=user.user_id,
        role=user.role,
    )
    return success(record.public_dict())


@router.get("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def get_skill(skill_id: str, user: ReadUser, service: SkillDep):
    record = await service.get(
        skill_id, user_id=user.user_id, role=user.role
    )
    payload = record.public_dict()
    payload["content"] = await service.read_content(
        skill_id, user_id=user.user_id, role=user.role
    )
    return success(payload)


@router.get("/api/skills/{skill_id}/files", response_model=ApiResponse[list[SkillFilePublic]])
async def list_skill_files(skill_id: str, user: ReadUser, service: SkillDep):
    return success(await service.list_files(
        skill_id, user_id=user.user_id, role=user.role
    ))


@router.get("/api/skills/{skill_id}/files/{path:path}")
async def read_skill_file(skill_id: str, path: str, user: ReadUser, service: SkillDep):
    content = await service.read_file(
        skill_id, path, user_id=user.user_id, role=user.role
    )
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.put("/api/skills/{skill_id}", response_model=ApiResponse[SkillPublic])
async def update_skill(
    skill_id: str, body: SkillUpdateBody, user: CurrentUser, service: SkillDep
):
    record = await service.update_content(
        skill_id, body.content, user_id=user.user_id, role=user.role
    )
    return success(record.public_dict())


@router.delete("/api/skills/{skill_id}", response_model=ApiResponse[None])
async def delete_skill(skill_id: str, user: CurrentUser, service: SkillDep):
    await service.disable(skill_id, user_id=user.user_id, role=user.role)
    return success()


@router.put(
    "/api/workspace/skills/{name}",
    response_model=ApiResponse[dict],
)
async def write_workspace_skill(
    name: str, body: WorkspaceSkillBody, user: CurrentUser, service: SkillDep,
    catalog: CatalogDep, agent_id: str = Query(min_length=1)
):
    await catalog.get_agent(user.user_id, agent_id)
    path = await service.write_workspace_skill(
        user_id=user.user_id, agent_id=agent_id, name=name, content=body.content
    )
    return success(
        {
            "name": name,
            "workspace_path": str(path),
            "status": await service.workspace_status(
                user_id=user.user_id, agent_id=agent_id, name=name
            ),
        }
    )
