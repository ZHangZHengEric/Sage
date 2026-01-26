from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ===== Common =====
class SuccessResponse(BaseModel):
    success: bool

# ===== KDB Models =====

class KdbAddRequest(BaseModel):
    name: str
    type: str
    intro: Optional[str] = ""
    language: Optional[str] = ""

class KdbAddResponse(BaseModel):
    kdb_id: str

class KdbUpdateRequest(BaseModel):
    kdb_id: str
    name: Optional[str] = ""
    intro: Optional[str] = ""
    kdb_setting: Optional[Dict[str, Any]] = None

class KdbInfoResponse(BaseModel):
    kdbId: str
    name: str
    intro: str
    createdAt: int
    updatedAt: int
    kdbSetting: Optional[Dict[str, Any]] = None

class KdbRetrieveRequest(BaseModel):
    kdb_id: str
    query: str
    top_k: int = 10

class KdbRetrieveResponse(BaseModel):
    # 根据业务逻辑，retrieve 返回检索结果列表
    # 这里为了通用性暂时定义为 Any，后续可根据 SearchResult 定义细化
    results: List[Dict[str, Any]]

class KdbListItem(BaseModel):
    id: str
    name: str
    index_name: str
    intro: str
    createTime: str
    dataSource: str
    docNum: int
    cover: str = ""
    defaultColor: bool = True
    creator: Optional[str] = None
    type: Optional[str] = None

class KdbListResponse(BaseModel):
    list: List[KdbListItem]
    total: int

class KdbIdRequest(BaseModel):
    kdb_id: str

# ===== Doc Models =====

class KdbDocListItem(BaseModel):
    id: str
    doc_name: str
    status: str
    create_time: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    task_id: str

class KdbDocListResponse(BaseModel):
    list: List[KdbDocListItem]
    total: int

class KdbDocInfoResponse(BaseModel):
    id: str
    type: str
    dataName: str
    status: str
    createTime: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    taskId: str

class KdbDocAddByFilesResponse(BaseModel):
    taskId: str

class KdbDocTaskProcessResponse(BaseModel):
    success: int
    fail: int
    inProgress: int
    waiting: int
    total: int
    taskProcess: float

class KdbDocTaskRedoRequest(BaseModel):
    kdb_id: str
    task_id: str
