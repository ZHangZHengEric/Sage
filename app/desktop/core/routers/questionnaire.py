from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel, Field

questionnaire_router = APIRouter(prefix="/api/questionnaires", tags=["Questionnaires"])

# 内存存储: session_id -> 问卷会话
_questionnaire_sessions: Dict[str, "QuestionnaireSession"] = {}


class QuestionOption(BaseModel):
    """问题选项"""
    label: str = Field(..., description="选项显示文本")
    value: str = Field(..., description="选项值")


class Question(BaseModel):
    """问题定义"""
    id: str = Field(..., description="问题唯一标识符")
    type: str = Field(..., description="问题类型: single_choice, multiple_choice, text")
    title: str = Field(..., description="问题标题")
    options: Optional[list[QuestionOption]] = Field(None, description="选项列表(单选/多选必填)")
    default: Optional[Any] = Field(None, description="默认值，单选为字符串，多选为字符串数组，文本题为空字符串")
    placeholder: Optional[str] = Field(None, description="文本输入框占位提示")
    max_length: Optional[int] = Field(1000, description="最大输入长度")


class SubmitAnswersRequest(BaseModel):
    """提交答案请求"""
    answers: Dict[str, Any] = Field(..., description="用户答案")
    title: Optional[str] = Field(None, description="问卷标题（首次提交时创建会话）")
    questions: Optional[list[Dict[str, Any]]] = Field(None, description="问题列表（首次提交时创建会话）")
    wait_time: int = Field(300, description="等待时间(秒)（首次提交时创建会话）")
    is_auto_submit: bool = Field(False, description="是否为自动提交（超时自动提交）")


class QuestionnaireSession(BaseModel):
    """问卷会话（内存存储）"""
    session_id: str
    title: str
    questions: list[Dict[str, Any]]
    status: str = "pending"  # pending, submitted, expired
    answers: Optional[Dict[str, Any]] = None
    submitted_at: Optional[datetime] = None
    expires_at: datetime
    is_auto_submit: bool = False  # 是否为自动提交


class QuestionnaireResponse(BaseModel):
    """问卷响应"""
    session_id: str
    status: str
    answers: Optional[Dict[str, Any]] = None
    submitted_at: Optional[datetime] = None
    is_auto_submit: bool = False  # 是否为自动提交


class SubmitResponse(BaseModel):
    """提交答案响应"""
    success: bool


@questionnaire_router.post("/session/{session_id}/submit", response_model=SubmitResponse)
async def submit_questionnaire(
    session_id: str = Path(..., description="会话ID"),
    data: SubmitAnswersRequest = Body(...)
):
    """前端提交问卷答案（如果会话不存在则自动创建）"""
    session = _questionnaire_sessions.get(session_id)
    
    if not session:
        # 会话不存在，需要创建
        if not data.title or not data.questions:
            raise HTTPException(status_code=400, detail="会话不存在，需要提供 title 和 questions 来创建会话")
        
        # 创建新会话
        expires_at = datetime.utcnow() + timedelta(seconds=data.wait_time)
        session = QuestionnaireSession(
            session_id=session_id,
            title=data.title,
            questions=data.questions,
            status="pending",
            expires_at=expires_at
        )
        _questionnaire_sessions[session_id] = session
    
    if session.status == "submitted":
        raise HTTPException(status_code=400, detail="问卷已提交")
    
    if session.status == "expired" or datetime.utcnow() > session.expires_at:
        session.status = "expired"
        raise HTTPException(status_code=400, detail="问卷已过期")
    
    # 提交答案
    session.answers = data.answers
    session.status = "submitted"
    session.submitted_at = datetime.utcnow()
    session.is_auto_submit = data.is_auto_submit
    
    return SubmitResponse(success=True)


@questionnaire_router.get("/session/{session_id}/results", response_model=QuestionnaireResponse)
async def get_questionnaire_results(
    session_id: str = Path(..., description="会话ID")
):
    """工具轮询获取问卷结果（通过 session_id）"""
    session = _questionnaire_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 检查是否过期
    if session.status == "pending" and datetime.utcnow() > session.expires_at:
        session.status = "expired"

    # 如果已提交，获取结果后删除会话
    if session.status == "submitted":
        result = QuestionnaireResponse(
            session_id=session.session_id,
            status=session.status,
            answers=session.answers,
            submitted_at=session.submitted_at,
            is_auto_submit=session.is_auto_submit
        )
        # 删除会话（清理内存）
        del _questionnaire_sessions[session_id]
        return result

    return QuestionnaireResponse(
        session_id=session.session_id,
        status=session.status,
        answers=session.answers,
        submitted_at=session.submitted_at,
        is_auto_submit=session.is_auto_submit
    )



