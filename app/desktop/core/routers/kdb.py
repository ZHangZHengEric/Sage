from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from sagents.tool.mcp_tool_base import sage_mcp_tool

from ..core.render import Response
from ..schemas.base import BaseResponse
from ..schemas.kdb import (
    KdbAddRequest,
    KdbAddResponse,
    KdbDocAddByFilesResponse,
    KdbDocInfoResponse,
    KdbDocListItem,
    KdbDocListResponse,
    KdbDocTaskProcessResponse,
    KdbDocTaskRedoRequest,
    KdbIdRequest,
    KdbInfoResponse,
    KdbListItem,
    KdbListResponse,
    KdbRetrieveRequest,
    KdbRetrieveResponse,
    KdbUpdateRequest,
    SuccessResponse,
)
from ..services.kdb import KdbService
from ..services.knowledge_base import DocumentService

kdb_router = APIRouter(prefix="/api/knowledge-base", tags=["KDB"])


# ===== KDB Management =====
@kdb_router.post("/add", response_model=BaseResponse[KdbAddResponse])
async def kdb_add(
    http_request: Request,
    req: KdbAddRequest,
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    kdb_id = await svc.add(
        name=req.name, 
        type=req.type, 
        intro=req.intro, 
        language=req.language, 
        user_id=user_id
    )
    return await Response.succ(data=KdbAddResponse(kdb_id=kdb_id, user_id=user_id))


@kdb_router.post("/update", response_model=BaseResponse[SuccessResponse])
async def kdb_update(req: KdbUpdateRequest, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.update(
        kdb_id=req.kdb_id, 
        name=req.name, 
        intro=req.intro, 
        kdb_setting=req.kdb_setting,
        user_id=check_user_id
    )
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


@kdb_router.get("/info", response_model=BaseResponse[KdbInfoResponse])
async def kdb_info(http_request: Request, kdb_id: str = Query(...)):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"

    check_user_id = user_id if role != "admin" else None

    obj = await svc.info(kdb_id, user_id=check_user_id)
    # svc.info raises 404/403 now, so obj is guaranteed to be valid if we reach here
    return await Response.succ(
        data=KdbInfoResponse(
            kdbId=obj.id,
            name=obj.name,
            intro=obj.intro,
            type=obj.data_type,
            createdAt=int(obj.created_at.timestamp()),
            updatedAt=int(obj.updated_at.timestamp()),
            kdbSetting=obj.setting,
            user_id=obj.user_id,
        )
    )


@kdb_router.post("/retrieve", response_model=BaseResponse[KdbRetrieveResponse])
async def kdb_retrieve(
    http_request: Request,
    req: KdbRetrieveRequest,
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    check_user_id = user_id if role != "admin" else None
    
    result, kdb = await svc.retrieve(
        kdb_id=req.kdb_id, query=req.query, top_k=req.top_k, user_id=check_user_id
    )
    return await Response.succ(data=KdbRetrieveResponse(results=result, user_id=kdb.user_id))


@kdb_router.get("/list", response_model=BaseResponse[KdbListResponse])
async def kdb_list(
    http_request: Request,
    query_name: str = Query(""),
    type: str = Query(""),
    page: int = Query(1),
    page_size: int = Query(20),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    
    # For list, if admin, they can see all. If user, only theirs.
    # The svc.list method handles filtering if user_id is passed.
    # If admin, we pass None to see all? Or does admin want to filter by user_id?
    # Current implementation:
    # user_id = claims.get("userid") or ""
    # items, total, counts = await svc.list(..., user_id=user_id)
    # This forces admin to see only their own KDBs if we pass user_id.
    # We should allow admin to see all.
    
    check_user_id = user_id if role != "admin" else None
    
    items, total, counts = await svc.list(
        query_name=query_name,
        type=type,
        page=page,
        page_size=page_size,
        user_id=check_user_id,
    )
    out_list = [
        KdbListItem(
            id=k.id,
            name=k.name,
            index_name=k.get_index_name(),
            intro=k.intro,
            createTime=k.created_at.isoformat(),
            dataSource=k.data_type,
            docNum=counts.get(k.id, 0),
            cover="",
            defaultColor=True,
            user_id=k.user_id,
            type=None,
        )
        for k in items
    ]
    return await Response.succ(data=KdbListResponse(list=out_list, total=total, user_id=user_id))


@kdb_router.delete("/delete/{kdb_id}", response_model=BaseResponse[SuccessResponse])
async def kdb_delete(kdb_id: str, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None
    
    kdb = await svc.delete(kdb_id, user_id=check_user_id)
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


@kdb_router.post("/clear", response_model=BaseResponse[SuccessResponse])
async def kdb_clear(req: KdbIdRequest, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.clear(req.kdb_id, user_id=check_user_id)
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


@kdb_router.post("/redo_all", response_model=BaseResponse[SuccessResponse])
async def kdb_redo_all(req: KdbIdRequest, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.redo_all(req.kdb_id, user_id=check_user_id)
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


# ===== KDB Doc =====
@kdb_router.get("/doc/list", response_model=BaseResponse[KdbDocListResponse])
async def kdb_doc_list(
    http_request: Request,
    kdb_id: str = Query(...),
    query_name: str = Query(""),
    query_status: List[int] | None = Query(None),
    task_id: str = Query(""),
    page_no: int = Query(1),
    page_size: int = Query(20),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    docs, total, kdb = await svc.doc_list(
        kdb_id=kdb_id,
        query_name=query_name,
        query_status=query_status or [],
        task_id=task_id,
        page_no=page_no,
        page_size=page_size,
        user_id=check_user_id,
    )
    items = [
        KdbDocListItem(
            id=d.id,
            doc_name=d.doc_name,
            status=d.status,
            create_time=d.created_at.isoformat(),
            metadata=d.meta_data,
            task_id=d.task_id,
        )
        for d in docs
    ]
    return await Response.succ(data=KdbDocListResponse(list=items, total=total, user_id=kdb.user_id))


@kdb_router.get("/doc/info/{doc_id}", response_model=BaseResponse[Optional[KdbDocInfoResponse]])
async def kdb_doc_info(doc_id: str, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    d, kdb = await svc.doc_info(doc_id=doc_id, user_id=check_user_id)
    if not d:
        return await Response.succ(data=None)
    
    # kdb should be present if d is present (enforced by service)
    kdb_user_id = kdb.user_id if kdb else ""

    return await Response.succ(
        data=KdbDocInfoResponse(
            id=d.id,
            type=d.data_source,
            dataName=d.doc_name,
            status=d.status,
            createTime=d.created_at.isoformat(),
            metadata=d.meta_data,
            taskId=d.task_id,
            user_id=kdb_user_id
        )
    )


@kdb_router.post("/doc/add_by_files", response_model=BaseResponse[KdbDocAddByFilesResponse])
async def kdb_doc_add_by_files(
    http_request: Request,
    kdb_id: str = Form(...),
    override: bool = Form(False),
    files: List[UploadFile] = File(...),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""

    task_id, kdb = await svc.doc_add_by_upload_files(kdb_id=kdb_id, files=files, override=override, user_id=user_id)
    return await Response.succ(data=KdbDocAddByFilesResponse(taskId=task_id, user_id=kdb.user_id))


@kdb_router.delete("/doc/delete/{doc_id}", response_model=BaseResponse[SuccessResponse])
async def kdb_doc_delete(doc_id: str, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.doc_delete(doc_id=doc_id, user_id=check_user_id)
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


@kdb_router.put("/doc/redo/{doc_id}", response_model=BaseResponse[SuccessResponse])
async def kdb_doc_redo(doc_id: str, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.doc_redo(doc_id=doc_id, user_id=check_user_id)
    # kdb might be None if doc not found but service handles it (though logic there was tricky)
    # If service raises exception for not found, we are good.
    # Service doc_redo checks kdb_doc. If not found, it logs and returns None (my modified code).
    # I should check if kdb is None.
    kdb_user_id = kdb.user_id if kdb else ""
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb_user_id))


@kdb_router.get("/doc/task_process", response_model=BaseResponse[KdbDocTaskProcessResponse])
async def kdb_doc_task_process(
    http_request: Request,
    kdb_id: str = Query(...), 
    task_id: str = Query(...)
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    success, fail, in_progress, waiting, total, task_process, kdb = await svc.task_process(
        kdb_id=kdb_id, task_id=task_id, user_id=check_user_id
    )
    return await Response.succ(
        data=KdbDocTaskProcessResponse(
            success=success,
            fail=fail,
            inProgress=in_progress,
            waiting=waiting,
            total=total,
            taskProcess=task_process,
            user_id=kdb.user_id
        )
    )


@kdb_router.post("/doc/task_redo", response_model=BaseResponse[SuccessResponse])
async def kdb_doc_task_redo(req: KdbDocTaskRedoRequest, http_request: Request):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    role = claims.get("role") or "user"
    check_user_id = user_id if role != "admin" else None

    kdb = await svc.task_redo(kdb_id=req.kdb_id, task_id=req.task_id, user_id=check_user_id)
    return await Response.succ(data=SuccessResponse(success=True, user_id=kdb.user_id))


@sage_mcp_tool(server_name="knowledge_base")
async def retrieve_on_zavixai_db(index_name: str, query: str, top_k: int = 5):
    """
    Search documents on ZavixAI knowledge database.
    
    Args:
        index_name: The name of the index to search. (required)
        query: Search query (required)
        top_k: Number of results (1-50, default 5)
    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing the search results.
    """
    return await DocumentService().doc_search(index_name, query, top_k)
