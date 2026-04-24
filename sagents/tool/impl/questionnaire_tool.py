import asyncio
import json
from urllib.parse import quote
from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger


class DesktopBackendClient:
    """Desktop 模式下使用的本地 HTTP 客户端"""
    
    def __init__(self):
        import os
        # 使用 SAGE_PORT 环境变量（后端启动时设置），默认 8000
        port = os.environ.get('SAGE_PORT', '8000')
        self.base_url = f"http://127.0.0.1:{port}"
    
    async def get(self, path: str):
        import httpx
        async with httpx.AsyncClient() as client:
            return await client.get(f"{self.base_url}{path}")
    
    async def post(self, path: str, json: dict = None):
        import httpx
        async with httpx.AsyncClient() as client:
            return await client.post(f"{self.base_url}{path}", json=json)


class QuestionnaireTool:
    """问卷工具 - 向用户展示问卷表单并收集答案"""

    def _get_backend_client(self, runtime_session_id: Optional[str] = None):
        """获取后端 API 客户端"""
        if not runtime_session_id:
            return None
        try:
            from sagents.session_runtime import get_global_session_manager
            session_manager = get_global_session_manager()
            session = session_manager.get(runtime_session_id)
            if session and session.session_context:
                # 检查是否有 backend_client（server 模式）
                backend_client = getattr(session.session_context, 'backend_client', None)
                if backend_client:
                    return backend_client
                # desktop 模式：使用本地 HTTP 客户端
                return DesktopBackendClient()
        except Exception as e:
            logger.warning(f"获取 backend_client 失败: {e}")
        return None

    @tool(
        description_i18n={
            "zh": "向用户展示问卷表单并收集答案。支持单选题、多选题和文本问答题。工具会等待用户提交或超时，然后返回答案。",
            "en": "Display a questionnaire form to the user and collect answers. Supports single choice, multiple choice, and text questions. Waits for user submission or timeout, then returns answers."
        },
        param_description_i18n={
            "title": {
                "zh": "问卷标题",
                "en": "Questionnaire title"
            },
            "questions": {
                "zh": "问题列表，每个问题包含 id, type, title, options, default 等字段",
                "en": "List of questions, each containing id, type, title, options, default, etc."
            },
            "wait_time": {
                "zh": "等待用户回答的最大时间(秒)，超时自动提交。默认300秒(5分钟)。",
                "en": "Maximum time to wait for user response in seconds. Auto-submit on timeout. Default is 300 seconds (5 minutes)."
            },
            "questionnaire_id": {
                "zh": "问卷ID，用于关联问卷结果。推荐使用该字段。",
                "en": "Questionnaire ID used to associate questionnaire results. Preferred field."
            },
            "questionnaire_kind": {
                "zh": "问卷类型。planning 阶段建议显式传入，例如 plan_information 或 plan_confirmation。",
                "en": "Questionnaire kind. In planning phase, explicitly pass values such as plan_information or plan_confirmation."
            }
        },
        param_schema={
            "title": {
                "type": "string",
                "description": "问卷标题"
            },
            "questions": {
                "type": "array",
                "description": "问题列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "问题唯一标识符"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["single_choice", "multiple_choice", "text"],
                            "description": "问题类型: single_choice(单选), multiple_choice(多选), text(文本)"
                        },
                        "title": {
                            "type": "string",
                            "description": "问题标题"
                        },
                        "options": {
                            "type": "array",
                            "description": "选项列表(单选/多选必填)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "选项显示文本"
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "选项值"
                                    }
                                },
                                "required": ["label", "value"]
                            }
                        },
                        "default": {
                            "anyOf": [
                                {"type": "string", "description": "单选或文本题的默认值"},
                                {"type": "array", "items": {"type": "string"}, "description": "多选题的默认值(字符串数组)"}
                            ],
                            "description": "默认值，单选为字符串，多选为字符串数组，文本题为空字符串"
                        },
                        "placeholder": {
                            "type": "string",
                            "description": "文本输入框的占位提示(仅文本题)"
                        },
                        "max_length": {
                            "type": "integer",
                            "description": "最大输入长度(仅文本题)",
                            "default": 1000
                        }
                    },
                    "required": ["id", "type", "title"]
                }
            },
            "wait_time": {
                "type": "integer",
                "description": "等待时间(秒)",
                "default": 300,
                "minimum": 0,
                "maximum": 3600
            },
            "questionnaire_id": {
                "type": "string",
                "description": "问卷ID"
            },
            "questionnaire_kind": {
                "type": "string",
                "enum": ["general", "plan_information", "plan_confirmation"],
                "description": "问卷类型",
                "default": "general"
            }
        }
    )
    async def questionnaire(
        self,
        title: str,
        questions: List[Dict[str, Any]],
        questionnaire_id: str,
        session_id: Optional[str] = None,
        wait_time: int = 300,
        questionnaire_kind: str = "general",
    ) -> str:
        """
        向用户展示问卷表单并收集答案。
        工具直接轮询后端检查问卷是否有结果，前端负责展示问卷。

        Args:
            title: 问卷标题
            questions: 问题列表
            questionnaire_id: 问卷ID
            session_id: 系统注入的当前运行时会话ID，仅用于获取 backend client
            wait_time: 等待时间(秒)，默认300秒
            questionnaire_kind: 问卷类型

        Returns:
            JSON 格式的用户答案
        """
        logger.info(
            f"QuestionnaireTool: questionnaire_id={questionnaire_id}, title={title}, "
            f"wait_time={wait_time}, questionnaire_kind={questionnaire_kind}"
        )

        # 验证问题格式
        self._validate_questions(questions)

        # 获取后端客户端
        backend_client = self._get_backend_client(session_id)
        if not backend_client:
            raise ValueError("Backend client not available")

        # 轮询等待用户提交结果（通过 questionnaire_id 关联）
        logger.info(f"QuestionnaireTool: 开始轮询等待用户提交. questionnaire_id={questionnaire_id}")
        result = await self._poll_for_result(backend_client, questionnaire_id, wait_time)

        if result is None:
            # 超时，使用默认值作为答案
            logger.warning(f"QuestionnaireTool: 问卷超时，使用默认值. questionnaire_id={questionnaire_id}")
            default_answers = self._get_default_answers(questions)
            return json.dumps({
                "success": True,
                "status": "timeout",
                "message": "用户未在指定时间内提交，使用默认值",
                "answers": default_answers,
                "questionnaire_kind": questionnaire_kind,
            }, ensure_ascii=False, indent=2)

        logger.info(f"QuestionnaireTool: 成功获取问卷答案. questionnaire_id={questionnaire_id}, is_auto_submit={result.get('is_auto_submit', False)}")
        return json.dumps({
            "success": True,
            "status": "submitted",
            "message": "用户已提交答案",
            "answers": result.get("answers", {}),
            "questionnaire_id": result.get("questionnaire_id", questionnaire_id),
            "submitted_at": result.get("submitted_at"),
            "is_auto_submit": result.get("is_auto_submit", False),
            "questionnaire_kind": questionnaire_kind,
        }, ensure_ascii=False, indent=2)

    def _validate_questions(self, questions: List[Dict[str, Any]]):
        """验证问题格式"""
        if not questions:
            raise ValueError("问题列表不能为空")

        for idx, q in enumerate(questions):
            if "id" not in q:
                raise ValueError(f"第 {idx + 1} 个问题缺少 id 字段")
            if "type" not in q:
                raise ValueError(f"第 {idx + 1} 个问题缺少 type 字段")
            if "title" not in q:
                raise ValueError(f"第 {idx + 1} 个问题缺少 title 字段")

            qtype = q["type"]
            if qtype not in ["single_choice", "multiple_choice", "text"]:
                raise ValueError(f"第 {idx + 1} 个问题类型无效: {qtype}")

            if qtype in ["single_choice", "multiple_choice"]:
                if "options" not in q or not q["options"]:
                    raise ValueError(f"第 {idx + 1} 个选择题缺少 options 字段")
                for opt_idx, opt in enumerate(q["options"]):
                    if "label" not in opt:
                        raise ValueError(f"第 {idx + 1} 个问题第 {opt_idx + 1} 个选项缺少 label 字段")
                    if "value" not in opt:
                        raise ValueError(f"第 {idx + 1} 个问题第 {opt_idx + 1} 个选项缺少 value 字段")

    def _get_default_answers(self, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """获取所有问题的默认值"""
        default_answers = {}
        for q in questions:
            qid = q["id"]
            qtype = q["type"]
            default_value = q.get("default")
            
            if qtype == "multiple_choice":
                # 多选题：默认值为数组或空数组
                default_answers[qid] = default_value if default_value is not None else []
            else:
                # 单选题或文本题：默认值为字符串或空字符串
                default_answers[qid] = default_value if default_value is not None else ""
        
        return default_answers

    async def _poll_for_result(
        self,
        backend_client,
        questionnaire_id: str,
        wait_time: int
    ) -> Optional[Dict[str, Any]]:
        """轮询等待用户提交结果（通过 questionnaire_id）"""
        poll_interval = 1  # 每秒检查一次
        elapsed = 0

        while elapsed < wait_time:
            try:
                # 通过 questionnaire_id 获取问卷结果
                encoded_questionnaire_id = quote(questionnaire_id, safe="")
                response = await backend_client.get(f"/api/questionnaires/{encoded_questionnaire_id}/results")
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "submitted":
                        # 获取成功后，后端会自动删除该问卷结果
                        return result
                elif response.status_code == 404:
                    # 还没有结果，继续等待
                    pass
                else:
                    logger.warning(f"轮询问卷结果失败: {response.status_code}")

            except Exception as e:
                logger.warning(f"轮询问卷结果时出错: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return None
