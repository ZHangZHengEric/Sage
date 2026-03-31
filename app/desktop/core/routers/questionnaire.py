from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from ..models.base import get_local_now
from ..models.questionnaire import QuestionnaireDao, QuestionnaireSession


questionnaire_router = APIRouter(prefix="/api/questionnaires", tags=["Questionnaires"])


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


class QuestionnaireResponse(BaseModel):
    """问卷响应"""

    questionnaire_id: str
    status: str
    answers: Optional[Dict[str, Any]] = None
    submitted_at: Optional[Any] = None
    is_auto_submit: bool = False


class SubmitResponse(BaseModel):
    """提交答案响应"""

    success: bool


async def _get_or_create_session(
    dao: QuestionnaireDao,
    questionnaire_id: str,
    data: SubmitAnswersRequest,
) -> QuestionnaireSession:
    session = await dao.get_session(questionnaire_id)
    if session:
        return session

    if not data.title or not data.questions:
        raise HTTPException(status_code=400, detail="会话不存在，需要提供 title 和 questions 来创建会话")

    session = QuestionnaireSession(
        id=questionnaire_id,
        title=data.title,
        questions=data.questions,
        status="pending",
        wait_time=data.wait_time,
        expires_at=get_local_now() + timedelta(seconds=data.wait_time),
    )
    await dao.create_session(session)
    return session


@questionnaire_router.post("/{questionnaire_id}/submit", response_model=SubmitResponse)
async def submit_questionnaire(
    questionnaire_id: str = Path(..., description="问卷ID"),
    data: SubmitAnswersRequest = Body(...),
):
    """前端提交问卷答案（如果问卷不存在则自动创建）"""

    dao = QuestionnaireDao()
    session = await _get_or_create_session(dao, questionnaire_id, data)

    now = get_local_now()
    if session.status == "submitted":
        raise HTTPException(status_code=400, detail="问卷已提交")

    if session.status == "expired" or now > session.expires_at:
        await dao.update_where(
            QuestionnaireSession,
            [QuestionnaireSession.id == questionnaire_id],
            {"status": "expired"},
        )
        raise HTTPException(status_code=400, detail="问卷已过期")

    success = await dao.submit_answers(
        session_id=questionnaire_id,
        answers=data.answers,
        is_auto_submit=data.is_auto_submit,
    )
    if not success:
        raise HTTPException(status_code=400, detail="问卷提交失败")

    return SubmitResponse(success=True)


@questionnaire_router.get("/{questionnaire_id}/results", response_model=QuestionnaireResponse)
async def get_questionnaire_results(
    questionnaire_id: str = Path(..., description="问卷ID"),
):
    """工具轮询获取问卷结果（通过 questionnaire_id）"""

    dao = QuestionnaireDao()
    session = await dao.get_session(questionnaire_id)
    if not session:
        raise HTTPException(status_code=404, detail="问卷不存在")

    if session.status == "pending" and get_local_now() > session.expires_at:
        await dao.update_where(
            QuestionnaireSession,
            [QuestionnaireSession.id == questionnaire_id],
            {"status": "expired"},
        )
        session.status = "expired"

    return QuestionnaireResponse(
        questionnaire_id=session.id,
        status=session.status,
        answers=session.answers,
        submitted_at=session.submitted_at,
        is_auto_submit=bool(getattr(session, "is_auto_submit", False)),
    )
