from datetime import datetime
from typing import Any, Dict, List, Optional

from core.render import Response
from fastapi import APIRouter, Body, File, Form, Query, Request, UploadFile
from service.kdb import KdbService

kdb_router = APIRouter(prefix="/api/knowledge-base", tags=["KDB"])


# ===== KDB Management =====
@kdb_router.post("/add")
async def kdb_add(
    http_request: Request,
    name: str = Body(...),
    type: str = Body(...),
    intro: Optional[str] = Body(""),
    language: Optional[str] = Body(""),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    kdb_id = await svc.add(
        name=name, type=type, intro=intro, language=language, user_id=user_id
    )
    return await Response.succ(data={"kdb_id": kdb_id})


@kdb_router.post("/update")
async def kdb_update(
    kdb_id: str = Body(...),
    name: str = Body(""),
    intro: str = Body(""),
    kdb_setting: Dict[str, Any] | None = Body(None),
):
    svc = KdbService()
    await svc.update(kdb_id=kdb_id, name=name, intro=intro, kdb_setting=kdb_setting)
    return await Response.succ(data={"success": True})


@kdb_router.get("/info")
async def kdb_info(kdb_id: str = Query(...)):
    svc = KdbService()
    obj = await svc.info(kdb_id)
    if not obj:
        now_ts = int(datetime.now().timestamp())
        return await Response.succ(
            data={
                "kdbId": kdb_id,
                "name": "",
                "intro": "",
                "createdAt": now_ts,
                "updatedAt": now_ts,
                "kdbSetting": None,
            }
        )
    return await Response.succ(
        data={
            "kdbId": obj.id,
            "name": obj.name,
            "intro": obj.intro,
            "createdAt": int(obj.created_at.timestamp()),
            "updatedAt": int(obj.updated_at.timestamp()),
            "kdbSetting": obj.setting,
        }
    )


@kdb_router.post("/retrieve")
async def kdb_retrieve(
    http_request: Request,
    kdb_id: str = Body(...),
    query: str = Body(...),
    top_k: int = Body(10),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    result = await svc.retrieve(
        kdb_id=kdb_id, query=query, top_k=top_k, user_id=user_id
    )
    return await Response.succ(data=result)


@kdb_router.get("/list")
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
    items, total, counts = await svc.list(
        query_name=query_name,
        type=type,
        page=page,
        page_size=page_size,
        user_id=user_id,
    )
    out_list = [
        {
            "id": k.id,
            "name": k.name,
            "index_name": k.get_index_name(),
            "intro": k.intro,
            "createTime": k.created_at.isoformat(),
            "dataSource": k.data_type,
            "docNum": counts.get(k.id, 0),
            "cover": "",
            "defaultColor": True,
            "creator": None,
            "type": None,
        }
        for k in items
    ]
    return await Response.succ(data={"list": out_list, "total": total})


@kdb_router.delete("/delete/{kdb_id}")
async def kdb_delete(kdb_id: str):
    svc = KdbService()
    await svc.delete(kdb_id)
    return await Response.succ(data={"success": True})


@kdb_router.post("/clear")
async def kdb_clear(kdb_id: str = Body(...)):
    svc = KdbService()
    await svc.clear(kdb_id)
    return await Response.succ(data={"success": True})


@kdb_router.post("/redo_all")
async def kdb_redo_all(kdb_id: str = Body(...)):
    svc = KdbService()
    await svc.redo_all(kdb_id)
    return await Response.succ(data={"success": True})


# ===== KDB Doc =====
@kdb_router.get("/doc/list")
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
    docs, total = await svc.doc_list(
        kdb_id=kdb_id,
        query_name=query_name,
        query_status=query_status or [],
        task_id=task_id,
        page_no=page_no,
        page_size=page_size,
        user_id=user_id,
    )
    items = [
        {
            "id": d.id,
            "doc_name": d.doc_name,
            "status": d.status,
            "create_time": d.created_at.isoformat(),
            "metadata": d.meta_data,
            "task_id": d.task_id,
        }
        for d in docs
    ]
    return await Response.succ(data={"list": items, "total": total})


@kdb_router.get("/doc/info/{doc_id}")
async def kdb_doc_info(doc_id: str):
    svc = KdbService()
    d = await svc.doc_info(doc_id=doc_id)
    if not d:
        return await Response.succ(data={})
    return await Response.succ(
        data={
            "id": d.id,
            "type": d.data_source,
            "dataName": d.doc_name,
            "status": d.status,
            "createTime": d.created_at.isoformat(),
            "metadata": d.meta_data,
            "taskId": d.task_id,
        }
    )


@kdb_router.post("/doc/add_by_files")
async def kdb_doc_add_by_files(
    http_request: Request,
    kdb_id: str = Form(...),
    override: bool = Form(False),
    files: List[UploadFile] = File(...),
):
    svc = KdbService()
    claims = getattr(http_request.state, "user_claims", {}) or {}
    user_id = claims.get("userid") or ""
    task_id = await svc.doc_add_by_upload_files(
        kdb_id=kdb_id, files=files, override=override, user_id=user_id
    )
    return await Response.succ(data={"taskId": task_id})


@kdb_router.delete("/doc/delete/{doc_id}")
async def kdb_doc_delete(doc_id: str):
    svc = KdbService()
    await svc.doc_delete(doc_id=doc_id)
    return await Response.succ(data={"success": True})


@kdb_router.put("/doc/redo/{doc_id}")
async def kdb_doc_redo(doc_id: str):
    svc = KdbService()
    await svc.doc_redo(doc_id=doc_id)
    return await Response.succ(data={"success": True})


@kdb_router.get("/doc/task_process")
async def kdb_doc_task_process(kdb_id: str = Query(...), task_id: str = Query(...)):
    svc = KdbService()
    success, fail, in_progress, waiting, total, task_process = await svc.task_process(
        kdb_id=kdb_id, task_id=task_id
    )
    return await Response.succ(
        data={
            "success": success,
            "fail": fail,
            "inProgress": in_progress,
            "waiting": waiting,
            "total": total,
            "taskProcess": task_process,
        }
    )


@kdb_router.post("/doc/task_redo")
async def kdb_doc_task_redo(kdb_id: str = Body(...), task_id: str = Body(...)):
    svc = KdbService()
    await svc.task_redo(kdb_id=kdb_id, task_id=task_id)
    return await Response.succ(data={"success": True})
