"""Runtime-owned localization for user-visible V2 errors and recovery prompts.

Machine identifiers, diagnostics, and ordinary successful Tool results remain
language-neutral.  Anything shown to a user is resolved here before it enters
an Interaction or terminal RuntimeEvent.
"""

from __future__ import annotations

from typing import Any

from sagents.v2.contracts.errors import RuntimeErrorInfo


SUPPORTED_LANGUAGES = ("zh", "en", "pt", "es", "fr", "de", "ja", "ko", "ru")


def normalize_language(value: str | None) -> str:
    language = str(value or "en").strip().lower().replace("-", "_")
    for supported in SUPPORTED_LANGUAGES:
        if language == supported or language.startswith(f"{supported}_"):
            return supported
    return "en"


_EN = {
    "recovery.title": "The agent needs your guidance",
    "recovery.question": "What should happen next?",
    "recovery.guidance": "Review the explanation, choose an action, and add any details that may help the agent continue.",
    "recovery.loop": "The agent repeated the same approach without making progress.",
    "recovery.max_steps": "The agent reached its step limit before completing the task.",
    "recovery.status_failed": "The agent reported failure without a non-recoverable runtime error.",
    "recovery.invalid_status": "The agent returned an unsupported execution status: {status}.",
    "recovery.missing_status": "The agent reached the step limit without reporting a valid execution status.",
    "recovery.tool_not_found": "The agent requested a Tool that is not available in this run.",
    "recovery.plain_text": "The agent produced several responses without making Tool progress.",
    "recovery.input_prompt": "Provide the information the agent needs to continue.",
    "recovery.direction_placeholder": "Add missing information or describe a different direction",
    "action.continue": "Continue with the current approach",
    "action.change_direction": "Change direction",
    "action.retry": "Try again",
    "action.cancel": "Stop this run",
    "action.submit": "Submit",
    "approval.title": "Approval required",
    "approval.tool_prompt": "Review the requested Tool call: {tool}.",
    "approval.guidance": "Review the operation and its risk before choosing an action.",
    "approval.risk": "This operation may change data or external state.",
    "recovery.uncertain_tool": "The Tool outcome could not be confirmed. Choose how to reconcile it.",
    "error.validation": "The request could not be processed because some information is invalid.",
    "error.conflict": "The operation conflicts with the current run state.",
    "error.policy_denied": "The operation was blocked by the active security policy.",
    "error.tool.declined": "The Tool call was declined by the user.",
    "error.authentication": "Authentication failed. Check the configured credentials.",
    "error.authorization": "The current user is not allowed to perform this operation.",
    "error.rate_limited": "The model provider is temporarily rate-limiting requests. Try again later.",
    "error.provider_transient": "The model or Tool provider is temporarily unavailable. Try again later.",
    "error.provider_permanent": "The model or Tool provider rejected the request. Check its configuration.",
    "error.resource_lost": "A required runtime resource is no longer available.",
    "error.unsupported_schema": "This saved run uses an unsupported data format.",
    "error.corrupt_state": "The saved run state is incomplete or corrupted and cannot be resumed safely.",
    "error.uncertain_side_effect": "The Tool outcome is unknown. Confirm the result before continuing.",
    "error.cancelled": "The operation was cancelled.",
    "error.internal": "An internal runtime error stopped the run. Diagnostic details were recorded.",
    "error.model.stream_incomplete": "The model connection ended before a complete response was received.",
    "error.model.empty_semantic_response": "The model returned token usage but no usable text, reasoning, or Tool call. Sage retried automatically but still received an empty response.",
    "error.model.provider_error": "The model provider could not complete the request.",
    "error.tool.provider_error": "The Tool provider could not complete the operation.",
    "error.tool.not_found": "The requested Tool is not available in this run.",
    "error.tool.arguments_invalid": "The Tool arguments are invalid. The agent may correct them and try again.",
    "error.budget.max_tokens": "The run reached its token budget and was stopped.",
    "error.budget.deadline": "The run reached its time limit and was stopped.",
    "error.agent.driver_crashed": "The agent runtime stopped unexpectedly. Diagnostic details were recorded.",
    "error.agent.child_suspended": "A delegated agent is waiting for user input.",
    "error.flow.node_not_found": "The workflow cannot continue because its current node is missing.",
    "error.flow.visit_budget_exhausted": "The workflow exceeded its safe node-visit limit.",
    "error.flow.node_failed": "A workflow node failed and the run was stopped.",
    "questionnaire.invalid_list": "Questions must be a non-empty list.",
    "questionnaire.invalid_object": "Question {index} must be an object.",
    "questionnaire.invalid_type": "Question {index} has an unsupported type.",
    "questionnaire.missing_title": "Question {index} requires a title.",
    "questionnaire.missing_options": "Question {index} requires at least one option.",
    "goal.create_instruction": "This Run is in goal mode. Before substantive execution, call goal_submit exactly once with the concrete goal and its acceptance criteria. The Run cannot finish until goal_complete succeeds.",
    "goal.verify_instruction": "Do not claim completion until every acceptance criterion has been checked. Call goal_complete only after verification; that Tool is the only successful completion gate for this Run.",
    "goal.explanation_required": "The goal is recorded as completed. In your next reply, briefly tell the user what was delivered, where to find or use it, what was actually verified, and any remaining limitations. Distinguish code inspection from executed tests; do not invent verification. Use natural language rather than narrating internal tool calls. Do not call goal_complete again.",
    "goal.complete_reason": "goal_complete succeeded and the result was reported.",
    "goal.create_required": "No active goal exists. Call goal_submit before continuing.",
    "goal.incomplete": "The active goal is not complete. Re-check every acceptance criterion and call goal_complete only after verification.",
    "plan.submitted_instruction": "The Plan has been approved and saved. Do not call goal_submit again; briefly report that approval before ending this Run.",
    "plan.explanation_required": "The Plan was approved; explain that it was saved before ending.",
    "plan.submitted_reason": "goal_submit succeeded after user approval.",
    "plan.required": "Plan mode cannot finish directly; complete the investigation and call goal_submit with the full Plan.",
    "tool_selection.index_instruction": "Additional policy-allowed tools are listed below without full schemas. If one is needed, call tool_expand_tools with its exact name, then use it on the next step.",
}


def _overlay(**values: str) -> dict[str, str]:
    return dict(values)


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": _EN,
    "zh": _overlay(
        **{
            "recovery.title": "Agent 需要你的引导",
            "recovery.question": "接下来应该怎么做？",
            "recovery.guidance": "请查看说明、选择后续操作，并补充有助于 Agent 继续的信息。",
            "recovery.loop": "Agent 重复了相同做法，但没有取得进展。",
            "recovery.max_steps": "Agent 在完成任务前已达到步骤上限。",
            "recovery.status_failed": "Agent 报告了失败，但没有发生不可恢复的运行时异常。",
            "recovery.invalid_status": "Agent 返回了不支持的执行状态：{status}。",
            "recovery.missing_status": "Agent 达到步骤上限时仍未报告有效的执行状态。",
            "recovery.tool_not_found": "Agent 请求了当前运行中不可用的工具。",
            "recovery.plain_text": "Agent 连续多次回复，但没有产生工具进展。",
            "recovery.input_prompt": "请提供 Agent 继续执行所需的信息。",
            "recovery.direction_placeholder": "补充缺失信息，或说明希望采用的新方向",
            "action.continue": "按当前方向继续",
            "action.change_direction": "改变方向",
            "action.retry": "重试",
            "action.cancel": "停止本次运行",
            "action.submit": "提交",
            "approval.title": "需要审批",
            "approval.tool_prompt": "请检查请求的工具调用：{tool}。",
            "approval.guidance": "请选择操作前先检查执行内容及其风险。",
            "approval.risk": "该操作可能会更改数据或外部状态。",
            "recovery.uncertain_tool": "无法确认工具执行结果，请选择核对方式。",
            "error.validation": "部分信息无效，无法处理该请求。",
            "error.conflict": "该操作与当前运行状态冲突。",
            "error.policy_denied": "该操作已被当前安全策略阻止。",
            "error.tool.declined": "用户已拒绝本次工具调用。",
            "error.authentication": "身份验证失败，请检查已配置的凭据。",
            "error.authorization": "当前用户无权执行该操作。",
            "error.rate_limited": "模型服务暂时限制请求频率，请稍后重试。",
            "error.provider_transient": "模型或工具服务暂时不可用，请稍后重试。",
            "error.provider_permanent": "模型或工具服务拒绝了请求，请检查相关配置。",
            "error.resource_lost": "运行所需的资源已不可用。",
            "error.unsupported_schema": "该运行使用了当前版本不支持的数据格式。",
            "error.corrupt_state": "保存的运行状态不完整或已损坏，无法安全恢复。",
            "error.uncertain_side_effect": "工具执行结果未知，请确认结果后再继续。",
            "error.cancelled": "操作已取消。",
            "error.internal": "内部运行时错误终止了本次运行，诊断信息已记录。",
            "error.model.stream_incomplete": "模型连接在返回完整响应前中断。",
            "error.model.empty_semantic_response": "模型报告已生成 Token，但没有返回可用的文本、推理或工具调用；Sage 自动重试后仍收到空响应。",
            "error.model.provider_error": "模型服务未能完成请求。",
            "error.tool.provider_error": "工具服务未能完成操作。",
            "error.tool.not_found": "当前运行中没有所请求的工具。",
            "error.tool.arguments_invalid": "工具参数无效，Agent 可以修正后重试。",
            "error.budget.max_tokens": "本次运行已达到 Token 预算并停止。",
            "error.budget.deadline": "本次运行已达到时间上限并停止。",
            "error.agent.driver_crashed": "Agent 运行时意外停止，诊断信息已记录。",
            "error.agent.child_suspended": "一个被委派的 Agent 正在等待用户输入。",
            "error.flow.node_not_found": "工作流当前节点缺失，无法继续。",
            "error.flow.visit_budget_exhausted": "工作流超过了安全节点访问上限。",
            "error.flow.node_failed": "工作流节点执行失败，本次运行已停止。",
            "questionnaire.invalid_list": "questions 必须是非空列表。",
            "questionnaire.invalid_object": "第 {index} 个问题必须是对象。",
            "questionnaire.invalid_type": "第 {index} 个问题类型不受支持。",
            "questionnaire.missing_title": "第 {index} 个问题缺少标题。",
            "questionnaire.missing_options": "第 {index} 个问题至少需要一个选项。",
            "goal.create_instruction": "当前 Run 处于目标模式。开始实质执行前，必须调用一次 goal_submit，写入明确目标和验收标准。只有 goal_complete 成功后 Run 才能结束。",
            "goal.verify_instruction": "在声称完成前逐项检查全部验收标准；只有验证通过后才能调用 goal_complete。该工具是本 Run 唯一的成功完成门禁。",
            "goal.explanation_required": "目标已记录为完成。请在下一条回复中简洁总结：完成了什么、交付物在哪里或如何使用、实际做了哪些验证，以及仍有哪些限制。区分代码检查和实际运行测试，不要编造验证结果。自然地向用户说明结果，不要播报内部工具调用，也不要再次调用 goal_complete。",
            "goal.complete_reason": "goal_complete 已成功，且完成结果已经报告。",
            "goal.create_required": "当前还没有活动目标，请先调用 goal_submit。",
            "goal.incomplete": "活动目标尚未完成。请重新检查每项验收标准，仅在验证通过后调用 goal_complete。",
            "plan.submitted_instruction": "计划已经获批并保存。不要再次调用 goal_submit；结束本 Run 前简要告知用户审批结果。",
            "plan.explanation_required": "计划已获批准；结束前请向用户说明计划已经保存。",
            "plan.submitted_reason": "goal_submit 已在用户批准后成功执行。",
            "plan.required": "计划模式不能直接结束；请完成调查并调用 goal_submit 提交完整计划。",
            "tool_selection.index_instruction": "下面列出的是其他已获策略允许、但暂未附带完整 Schema 的工具。如需使用，请先用准确名称调用 tool_expand_tools，再在下一步调用该工具。",
        }
    ),
    "pt": _overlay(
        **{
            "recovery.title": "O agente precisa da sua orientação",
            "recovery.question": "O que deve acontecer a seguir?",
            "recovery.guidance": "Revise a explicação, escolha uma ação e acrescente detalhes para o agente continuar.",
            "recovery.loop": "O agente repetiu a mesma abordagem sem progredir.",
            "recovery.max_steps": "O agente atingiu o limite de etapas antes de concluir a tarefa.",
            "recovery.status_failed": "O agente relatou falha sem um erro de execução irrecuperável.",
            "recovery.invalid_status": "O agente retornou um estado não suportado: {status}.",
            "recovery.missing_status": "O agente atingiu o limite sem informar um estado válido.",
            "recovery.tool_not_found": "O agente solicitou uma ferramenta indisponível nesta execução.",
            "recovery.input_prompt": "Forneça as informações necessárias para o agente continuar.",
            "action.continue": "Continuar na direção atual",
            "action.change_direction": "Mudar de direção",
            "action.retry": "Tentar novamente",
            "action.cancel": "Parar esta execução",
            "action.submit": "Enviar",
            "error.validation": "A solicitação contém informações inválidas.",
            "error.tool.declined": "A chamada da ferramenta foi recusada pelo usuário.",
            "error.authentication": "Falha de autenticação. Verifique as credenciais configuradas.",
            "error.authorization": "O usuário atual não tem permissão para esta operação.",
            "error.rate_limited": "O provedor está limitando solicitações temporariamente. Tente mais tarde.",
            "error.provider_transient": "O provedor está temporariamente indisponível. Tente mais tarde.",
            "error.provider_permanent": "O provedor rejeitou a solicitação. Verifique a configuração.",
            "error.internal": "Um erro interno interrompeu a execução. Os diagnósticos foram registrados.",
            "error.tool.not_found": "A ferramenta solicitada não está disponível nesta execução.",
            "error.budget.max_tokens": "A execução atingiu o orçamento de tokens e foi interrompida.",
            "error.budget.deadline": "A execução atingiu o limite de tempo e foi interrompida.",
            "questionnaire.invalid_list": "As perguntas devem formar uma lista não vazia.",
        }
    ),
    "es": _overlay(
        **{
            "recovery.title": "El agente necesita tu orientación",
            "recovery.question": "¿Qué debe ocurrir a continuación?",
            "recovery.guidance": "Revisa la explicación, elige una acción y añade los detalles necesarios.",
            "recovery.loop": "El agente repitió el mismo enfoque sin avanzar.",
            "recovery.max_steps": "El agente alcanzó el límite de pasos antes de completar la tarea.",
            "recovery.status_failed": "El agente informó de un fallo sin un error irrecuperable.",
            "recovery.invalid_status": "El agente devolvió un estado no compatible: {status}.",
            "recovery.missing_status": "El agente alcanzó el límite sin informar de un estado válido.",
            "recovery.tool_not_found": "El agente solicitó una herramienta no disponible en esta ejecución.",
            "recovery.input_prompt": "Proporciona la información que el agente necesita para continuar.",
            "action.continue": "Continuar con el enfoque actual",
            "action.change_direction": "Cambiar de dirección",
            "action.retry": "Volver a intentar",
            "action.cancel": "Detener esta ejecución",
            "action.submit": "Enviar",
            "error.validation": "La solicitud contiene información no válida.",
            "error.tool.declined": "El usuario rechazó la llamada a la herramienta.",
            "error.authentication": "Falló la autenticación. Revisa las credenciales.",
            "error.authorization": "El usuario actual no puede realizar esta operación.",
            "error.rate_limited": "El proveedor limita temporalmente las solicitudes. Inténtalo más tarde.",
            "error.provider_transient": "El proveedor no está disponible temporalmente. Inténtalo más tarde.",
            "error.provider_permanent": "El proveedor rechazó la solicitud. Revisa la configuración.",
            "error.internal": "Un error interno detuvo la ejecución. Se guardaron los diagnósticos.",
            "error.tool.not_found": "La herramienta solicitada no está disponible en esta ejecución.",
            "error.budget.max_tokens": "La ejecución alcanzó su presupuesto de tokens y se detuvo.",
            "error.budget.deadline": "La ejecución alcanzó su límite de tiempo y se detuvo.",
            "questionnaire.invalid_list": "Las preguntas deben formar una lista no vacía.",
        }
    ),
    "fr": _overlay(
        **{
            "recovery.title": "L’agent a besoin de vos instructions",
            "recovery.question": "Que faut-il faire ensuite ?",
            "recovery.guidance": "Consultez l’explication, choisissez une action et ajoutez les détails utiles.",
            "recovery.loop": "L’agent a répété la même approche sans progresser.",
            "recovery.max_steps": "L’agent a atteint la limite d’étapes avant de terminer la tâche.",
            "recovery.status_failed": "L’agent a signalé un échec sans erreur d’exécution irrécupérable.",
            "recovery.invalid_status": "L’agent a renvoyé un état non pris en charge : {status}.",
            "recovery.missing_status": "L’agent a atteint la limite sans fournir d’état valide.",
            "recovery.tool_not_found": "L’agent a demandé un outil indisponible pour cette exécution.",
            "recovery.input_prompt": "Fournissez les informations nécessaires pour poursuivre.",
            "action.continue": "Continuer avec l’approche actuelle",
            "action.change_direction": "Changer de direction",
            "action.retry": "Réessayer",
            "action.cancel": "Arrêter cette exécution",
            "action.submit": "Envoyer",
            "error.validation": "La demande contient des informations non valides.",
            "error.tool.declined": "L’utilisateur a refusé l’appel de l’outil.",
            "error.authentication": "Échec de l’authentification. Vérifiez les identifiants.",
            "error.authorization": "L’utilisateur actuel n’est pas autorisé à effectuer cette opération.",
            "error.rate_limited": "Le fournisseur limite temporairement les requêtes. Réessayez plus tard.",
            "error.provider_transient": "Le fournisseur est temporairement indisponible. Réessayez plus tard.",
            "error.provider_permanent": "Le fournisseur a refusé la demande. Vérifiez sa configuration.",
            "error.internal": "Une erreur interne a arrêté l’exécution. Les diagnostics ont été enregistrés.",
            "error.tool.not_found": "L’outil demandé n’est pas disponible pour cette exécution.",
            "error.budget.max_tokens": "L’exécution a atteint son budget de jetons et a été arrêtée.",
            "error.budget.deadline": "L’exécution a atteint sa limite de temps et a été arrêtée.",
            "questionnaire.invalid_list": "Les questions doivent former une liste non vide.",
        }
    ),
    "de": _overlay(
        **{
            "recovery.title": "Der Agent benötigt Ihre Anleitung",
            "recovery.question": "Was soll als Nächstes geschehen?",
            "recovery.guidance": "Prüfen Sie die Erklärung, wählen Sie eine Aktion und ergänzen Sie hilfreiche Details.",
            "recovery.loop": "Der Agent hat denselben Ansatz ohne Fortschritt wiederholt.",
            "recovery.max_steps": "Der Agent hat vor Abschluss der Aufgabe das Schrittlimit erreicht.",
            "recovery.status_failed": "Der Agent meldete einen Fehler ohne nicht behebbaren Laufzeitfehler.",
            "recovery.invalid_status": "Der Agent gab einen nicht unterstützten Status zurück: {status}.",
            "recovery.missing_status": "Der Agent erreichte das Limit ohne gültigen Status.",
            "recovery.tool_not_found": "Der Agent forderte ein in diesem Lauf nicht verfügbares Werkzeug an.",
            "recovery.input_prompt": "Geben Sie die Informationen an, die der Agent zum Fortfahren benötigt.",
            "action.continue": "Mit dem aktuellen Ansatz fortfahren",
            "action.change_direction": "Richtung ändern",
            "action.retry": "Erneut versuchen",
            "action.cancel": "Diesen Lauf stoppen",
            "action.submit": "Senden",
            "error.validation": "Die Anfrage enthält ungültige Angaben.",
            "error.tool.declined": "Der Werkzeugaufruf wurde vom Benutzer abgelehnt.",
            "error.authentication": "Authentifizierung fehlgeschlagen. Prüfen Sie die Zugangsdaten.",
            "error.authorization": "Der aktuelle Benutzer darf diese Aktion nicht ausführen.",
            "error.rate_limited": "Der Anbieter begrenzt Anfragen vorübergehend. Versuchen Sie es später erneut.",
            "error.provider_transient": "Der Anbieter ist vorübergehend nicht verfügbar. Versuchen Sie es später erneut.",
            "error.provider_permanent": "Der Anbieter hat die Anfrage abgelehnt. Prüfen Sie die Konfiguration.",
            "error.internal": "Ein interner Fehler hat den Lauf beendet. Diagnosedaten wurden gespeichert.",
            "error.tool.not_found": "Das angeforderte Werkzeug ist in diesem Lauf nicht verfügbar.",
            "error.budget.max_tokens": "Der Lauf hat sein Token-Budget erreicht und wurde beendet.",
            "error.budget.deadline": "Der Lauf hat sein Zeitlimit erreicht und wurde beendet.",
            "questionnaire.invalid_list": "Die Fragen müssen als nicht leere Liste angegeben werden.",
        }
    ),
    "ja": _overlay(
        **{
            "recovery.title": "エージェントに指示が必要です",
            "recovery.question": "次にどうしますか？",
            "recovery.guidance": "説明を確認し、次の操作を選び、続行に役立つ情報を追加してください。",
            "recovery.loop": "エージェントが同じ方法を繰り返し、進展がありませんでした。",
            "recovery.max_steps": "タスク完了前にステップ上限に達しました。",
            "recovery.status_failed": "回復不能な実行時エラーなしに、エージェントが失敗を報告しました。",
            "recovery.invalid_status": "未対応の実行状態が返されました：{status}。",
            "recovery.missing_status": "有効な実行状態を報告せずにステップ上限に達しました。",
            "recovery.tool_not_found": "この実行で利用できないツールが要求されました。",
            "recovery.input_prompt": "続行に必要な情報を入力してください。",
            "action.continue": "現在の方針で続ける",
            "action.change_direction": "方針を変更する",
            "action.retry": "再試行する",
            "action.cancel": "この実行を停止する",
            "action.submit": "送信",
            "error.validation": "無効な情報があるため、要求を処理できませんでした。",
            "error.tool.declined": "ユーザーがツール呼び出しを拒否しました。",
            "error.authentication": "認証に失敗しました。認証情報を確認してください。",
            "error.authorization": "現在のユーザーにはこの操作の権限がありません。",
            "error.rate_limited": "プロバイダーが一時的に要求を制限しています。後で再試行してください。",
            "error.provider_transient": "プロバイダーが一時的に利用できません。後で再試行してください。",
            "error.provider_permanent": "プロバイダーが要求を拒否しました。設定を確認してください。",
            "error.internal": "内部エラーで実行が停止しました。診断情報は記録されています。",
            "error.tool.not_found": "要求されたツールはこの実行では利用できません。",
            "error.budget.max_tokens": "トークン予算に達したため実行を停止しました。",
            "error.budget.deadline": "時間制限に達したため実行を停止しました。",
            "questionnaire.invalid_list": "質問は空でないリストで指定してください。",
        }
    ),
    "ko": _overlay(
        **{
            "recovery.title": "에이전트에 사용자의 안내가 필요합니다",
            "recovery.question": "다음에 무엇을 할까요?",
            "recovery.guidance": "설명을 확인하고 다음 작업을 선택한 뒤 계속하는 데 필요한 정보를 추가하세요.",
            "recovery.loop": "에이전트가 같은 접근을 반복했지만 진전이 없었습니다.",
            "recovery.max_steps": "작업을 완료하기 전에 단계 제한에 도달했습니다.",
            "recovery.status_failed": "복구 불가능한 런타임 오류 없이 에이전트가 실패를 보고했습니다.",
            "recovery.invalid_status": "지원하지 않는 실행 상태가 반환되었습니다: {status}.",
            "recovery.missing_status": "유효한 실행 상태를 보고하지 않고 단계 제한에 도달했습니다.",
            "recovery.tool_not_found": "현재 실행에서 사용할 수 없는 도구를 요청했습니다.",
            "recovery.input_prompt": "계속하는 데 필요한 정보를 입력하세요.",
            "action.continue": "현재 방식으로 계속",
            "action.change_direction": "방향 변경",
            "action.retry": "다시 시도",
            "action.cancel": "이 실행 중지",
            "action.submit": "제출",
            "error.validation": "일부 정보가 유효하지 않아 요청을 처리할 수 없습니다.",
            "error.tool.declined": "사용자가 도구 호출을 거부했습니다.",
            "error.authentication": "인증에 실패했습니다. 자격 증명을 확인하세요.",
            "error.authorization": "현재 사용자는 이 작업을 수행할 수 없습니다.",
            "error.rate_limited": "공급자가 일시적으로 요청을 제한하고 있습니다. 나중에 다시 시도하세요.",
            "error.provider_transient": "공급자를 일시적으로 사용할 수 없습니다. 나중에 다시 시도하세요.",
            "error.provider_permanent": "공급자가 요청을 거부했습니다. 설정을 확인하세요.",
            "error.internal": "내부 오류로 실행이 중지되었습니다. 진단 정보가 기록되었습니다.",
            "error.tool.not_found": "요청한 도구는 현재 실행에서 사용할 수 없습니다.",
            "error.budget.max_tokens": "토큰 예산에 도달하여 실행이 중지되었습니다.",
            "error.budget.deadline": "시간 제한에 도달하여 실행이 중지되었습니다.",
            "questionnaire.invalid_list": "질문은 비어 있지 않은 목록이어야 합니다.",
        }
    ),
    "ru": _overlay(
        **{
            "recovery.title": "Агенту нужны ваши указания",
            "recovery.question": "Что сделать дальше?",
            "recovery.guidance": "Прочитайте объяснение, выберите действие и добавьте сведения для продолжения.",
            "recovery.loop": "Агент повторял один и тот же подход без прогресса.",
            "recovery.max_steps": "Агент достиг лимита шагов до завершения задачи.",
            "recovery.status_failed": "Агент сообщил о сбое без неисправимой ошибки среды выполнения.",
            "recovery.invalid_status": "Агент вернул неподдерживаемое состояние: {status}.",
            "recovery.missing_status": "Агент достиг лимита, не сообщив допустимое состояние.",
            "recovery.tool_not_found": "Агент запросил инструмент, недоступный в этом запуске.",
            "recovery.input_prompt": "Укажите сведения, необходимые агенту для продолжения.",
            "action.continue": "Продолжить текущим способом",
            "action.change_direction": "Изменить направление",
            "action.retry": "Повторить попытку",
            "action.cancel": "Остановить запуск",
            "action.submit": "Отправить",
            "error.validation": "Запрос содержит недопустимые данные.",
            "error.tool.declined": "Пользователь отклонил вызов инструмента.",
            "error.authentication": "Ошибка аутентификации. Проверьте учётные данные.",
            "error.authorization": "Текущему пользователю не разрешена эта операция.",
            "error.rate_limited": "Поставщик временно ограничивает запросы. Повторите позже.",
            "error.provider_transient": "Поставщик временно недоступен. Повторите позже.",
            "error.provider_permanent": "Поставщик отклонил запрос. Проверьте настройки.",
            "error.internal": "Внутренняя ошибка остановила запуск. Диагностика сохранена.",
            "error.tool.not_found": "Запрошенный инструмент недоступен в этом запуске.",
            "error.budget.max_tokens": "Запуск достиг бюджета токенов и был остановлен.",
            "error.budget.deadline": "Запуск достиг ограничения времени и был остановлен.",
            "questionnaire.invalid_list": "Вопросы должны быть непустым списком.",
        }
    ),
}


# Keep every supported locale semantically complete.  These entries are kept
# together because they cover the less common recovery and infrastructure
# paths that are easy to miss when adding a locale.
_COMPLETE_LOCALE_TEXT: dict[str, dict[str, str]] = {
    "pt": {
        "tool_selection.index_instruction": "Outras ferramentas permitidas pela política aparecem abaixo sem o esquema completo. Se precisar de uma, chame tool_expand_tools com o nome exato e use-a na etapa seguinte.",
        "approval.title": "Aprovação necessária",
        "approval.tool_prompt": "Revise a chamada de ferramenta solicitada: {tool}.",
        "approval.guidance": "Revise a operação e o risco antes de escolher uma ação.",
        "approval.risk": "Esta operação pode alterar dados ou estado externo.",
        "recovery.uncertain_tool": "Não foi possível confirmar o resultado da ferramenta. Escolha como verificá-lo.",
        "recovery.plain_text": "O agente produziu várias respostas sem avançar com ferramentas.",
        "recovery.direction_placeholder": "Adicione informações ausentes ou descreva outra direção",
        "error.conflict": "A operação entra em conflito com o estado atual da execução.",
        "error.policy_denied": "A operação foi bloqueada pela política de segurança ativa.",
        "error.resource_lost": "Um recurso necessário para a execução não está mais disponível.",
        "error.unsupported_schema": "A execução salva usa um formato de dados não compatível.",
        "error.corrupt_state": "O estado salvo está incompleto ou corrompido e não pode ser retomado com segurança.",
        "error.uncertain_side_effect": "O resultado da ferramenta é desconhecido. Confirme-o antes de continuar.",
        "error.cancelled": "A operação foi cancelada.",
        "error.model.stream_incomplete": "A conexão com o modelo terminou antes de uma resposta completa.",
        "error.model.empty_semantic_response": "O modelo informou uso de tokens, mas não retornou texto, raciocínio ou chamada de ferramenta utilizável; o Sage tentou novamente automaticamente e ainda recebeu uma resposta vazia.",
        "error.model.provider_error": "O provedor do modelo não concluiu a solicitação.",
        "error.tool.provider_error": "O provedor da ferramenta não concluiu a operação.",
        "error.tool.arguments_invalid": "Os argumentos da ferramenta são inválidos. O agente pode corrigi-los e tentar novamente.",
        "error.agent.driver_crashed": "O runtime do agente parou inesperadamente. Os diagnósticos foram registrados.",
        "error.agent.child_suspended": "Um agente delegado está aguardando uma resposta do usuário.",
        "error.flow.node_not_found": "O fluxo não pode continuar porque o nó atual não existe.",
        "error.flow.visit_budget_exhausted": "O fluxo excedeu o limite seguro de visitas a nós.",
        "error.flow.node_failed": "Um nó do fluxo falhou e a execução foi interrompida.",
        "questionnaire.invalid_object": "A pergunta {index} deve ser um objeto.",
        "questionnaire.invalid_type": "A pergunta {index} tem um tipo não compatível.",
        "questionnaire.missing_title": "A pergunta {index} precisa de um título.",
        "questionnaire.missing_options": "A pergunta {index} precisa de pelo menos uma opção.",
    },
    "es": {
        "tool_selection.index_instruction": "A continuación se muestran otras herramientas permitidas sin sus esquemas completos. Si necesitas una, llama a tool_expand_tools con su nombre exacto y úsala en el siguiente paso.",
        "approval.title": "Se requiere aprobación",
        "approval.tool_prompt": "Revisa la llamada a la herramienta solicitada: {tool}.",
        "approval.guidance": "Revisa la operación y su riesgo antes de elegir una acción.",
        "approval.risk": "Esta operación puede modificar datos o estado externo.",
        "recovery.uncertain_tool": "No se pudo confirmar el resultado de la herramienta. Elige cómo comprobarlo.",
        "recovery.plain_text": "El agente produjo varias respuestas sin avanzar con herramientas.",
        "recovery.direction_placeholder": "Añade la información que falta o describe otra dirección",
        "error.conflict": "La operación entra en conflicto con el estado actual de la ejecución.",
        "error.policy_denied": "La política de seguridad activa bloqueó la operación.",
        "error.resource_lost": "Un recurso necesario para la ejecución ya no está disponible.",
        "error.unsupported_schema": "La ejecución guardada usa un formato de datos no compatible.",
        "error.corrupt_state": "El estado guardado está incompleto o dañado y no puede reanudarse de forma segura.",
        "error.uncertain_side_effect": "Se desconoce el resultado de la herramienta. Confírmalo antes de continuar.",
        "error.cancelled": "La operación fue cancelada.",
        "error.model.stream_incomplete": "La conexión con el modelo terminó antes de recibir una respuesta completa.",
        "error.model.empty_semantic_response": "El modelo informó uso de tokens, pero no devolvió texto, razonamiento ni una llamada de herramienta utilizable; Sage reintentó automáticamente y siguió recibiendo una respuesta vacía.",
        "error.model.provider_error": "El proveedor del modelo no pudo completar la solicitud.",
        "error.tool.provider_error": "El proveedor de la herramienta no pudo completar la operación.",
        "error.tool.arguments_invalid": "Los argumentos de la herramienta no son válidos. El agente puede corregirlos y reintentar.",
        "error.agent.driver_crashed": "El runtime del agente se detuvo inesperadamente. Se guardaron los diagnósticos.",
        "error.agent.child_suspended": "Un agente delegado está esperando una respuesta del usuario.",
        "error.flow.node_not_found": "El flujo no puede continuar porque falta el nodo actual.",
        "error.flow.visit_budget_exhausted": "El flujo superó el límite seguro de visitas a nodos.",
        "error.flow.node_failed": "Falló un nodo del flujo y se detuvo la ejecución.",
        "questionnaire.invalid_object": "La pregunta {index} debe ser un objeto.",
        "questionnaire.invalid_type": "La pregunta {index} tiene un tipo no compatible.",
        "questionnaire.missing_title": "La pregunta {index} requiere un título.",
        "questionnaire.missing_options": "La pregunta {index} requiere al menos una opción.",
    },
    "fr": {
        "tool_selection.index_instruction": "D’autres outils autorisés sont listés ci-dessous sans leur schéma complet. Si nécessaire, appelez tool_expand_tools avec le nom exact, puis utilisez l’outil à l’étape suivante.",
        "approval.title": "Approbation requise",
        "approval.tool_prompt": "Vérifiez l’appel d’outil demandé : {tool}.",
        "approval.guidance": "Examinez l’opération et son risque avant de choisir une action.",
        "approval.risk": "Cette opération peut modifier des données ou un état externe.",
        "recovery.uncertain_tool": "Le résultat de l’outil n’a pas pu être confirmé. Choisissez comment le vérifier.",
        "recovery.plain_text": "L’agent a produit plusieurs réponses sans progresser avec les outils.",
        "recovery.direction_placeholder": "Ajoutez les informations manquantes ou indiquez une autre direction",
        "error.conflict": "L’opération est incompatible avec l’état actuel de l’exécution.",
        "error.policy_denied": "L’opération a été bloquée par la politique de sécurité active.",
        "error.resource_lost": "Une ressource nécessaire à l’exécution n’est plus disponible.",
        "error.unsupported_schema": "L’exécution enregistrée utilise un format de données non pris en charge.",
        "error.corrupt_state": "L’état enregistré est incomplet ou endommagé et ne peut pas être repris en toute sécurité.",
        "error.uncertain_side_effect": "Le résultat de l’outil est inconnu. Confirmez-le avant de continuer.",
        "error.cancelled": "L’opération a été annulée.",
        "error.model.stream_incomplete": "La connexion au modèle s’est interrompue avant une réponse complète.",
        "error.model.empty_semantic_response": "Le modèle a signalé des jetons générés sans renvoyer de texte, de raisonnement ni d’appel d’outil exploitable ; Sage a réessayé automatiquement, mais a encore reçu une réponse vide.",
        "error.model.provider_error": "Le fournisseur du modèle n’a pas pu terminer la demande.",
        "error.tool.provider_error": "Le fournisseur de l’outil n’a pas pu terminer l’opération.",
        "error.tool.arguments_invalid": "Les arguments de l’outil sont invalides. L’agent peut les corriger et réessayer.",
        "error.agent.driver_crashed": "Le runtime de l’agent s’est arrêté de façon inattendue. Les diagnostics ont été enregistrés.",
        "error.agent.child_suspended": "Un agent délégué attend une réponse de l’utilisateur.",
        "error.flow.node_not_found": "Le flux ne peut pas continuer, car le nœud actuel est absent.",
        "error.flow.visit_budget_exhausted": "Le flux a dépassé la limite sûre de visites de nœuds.",
        "error.flow.node_failed": "Un nœud du flux a échoué et l’exécution a été arrêtée.",
        "questionnaire.invalid_object": "La question {index} doit être un objet.",
        "questionnaire.invalid_type": "Le type de la question {index} n’est pas pris en charge.",
        "questionnaire.missing_title": "La question {index} nécessite un titre.",
        "questionnaire.missing_options": "La question {index} nécessite au moins une option.",
    },
    "de": {
        "tool_selection.index_instruction": "Weitere zulässige Werkzeuge sind unten ohne vollständiges Schema aufgeführt. Rufen Sie bei Bedarf tool_expand_tools mit dem exakten Namen auf und verwenden Sie das Werkzeug im nächsten Schritt.",
        "approval.title": "Genehmigung erforderlich",
        "approval.tool_prompt": "Prüfen Sie den angeforderten Werkzeugaufruf: {tool}.",
        "approval.guidance": "Prüfen Sie Vorgang und Risiko, bevor Sie eine Aktion wählen.",
        "approval.risk": "Dieser Vorgang kann Daten oder externen Zustand verändern.",
        "recovery.uncertain_tool": "Das Werkzeugergebnis konnte nicht bestätigt werden. Wählen Sie eine Prüfmethode.",
        "recovery.plain_text": "Der Agent hat mehrere Antworten erzeugt, ohne mit Werkzeugen voranzukommen.",
        "recovery.direction_placeholder": "Ergänzen Sie fehlende Angaben oder beschreiben Sie eine andere Richtung",
        "error.conflict": "Die Operation steht im Konflikt mit dem aktuellen Ausführungsstatus.",
        "error.policy_denied": "Die aktive Sicherheitsrichtlinie hat die Operation blockiert.",
        "error.resource_lost": "Eine erforderliche Laufzeitressource ist nicht mehr verfügbar.",
        "error.unsupported_schema": "Der gespeicherte Lauf verwendet ein nicht unterstütztes Datenformat.",
        "error.corrupt_state": "Der gespeicherte Zustand ist unvollständig oder beschädigt und kann nicht sicher fortgesetzt werden.",
        "error.uncertain_side_effect": "Das Ergebnis des Werkzeugs ist unbekannt. Bestätigen Sie es vor dem Fortfahren.",
        "error.cancelled": "Die Operation wurde abgebrochen.",
        "error.model.stream_incomplete": "Die Modellverbindung endete, bevor eine vollständige Antwort einging.",
        "error.model.empty_semantic_response": "Das Modell meldete erzeugte Tokens, lieferte aber weder nutzbaren Text noch Reasoning oder einen Tool-Aufruf; Sage hat automatisch erneut versucht und weiterhin eine leere Antwort erhalten.",
        "error.model.provider_error": "Der Modellanbieter konnte die Anfrage nicht abschließen.",
        "error.tool.provider_error": "Der Werkzeuganbieter konnte die Operation nicht abschließen.",
        "error.tool.arguments_invalid": "Die Werkzeugargumente sind ungültig. Der Agent kann sie korrigieren und erneut versuchen.",
        "error.agent.driver_crashed": "Die Agent-Laufzeit wurde unerwartet beendet. Diagnosedaten wurden gespeichert.",
        "error.agent.child_suspended": "Ein delegierter Agent wartet auf eine Benutzereingabe.",
        "error.flow.node_not_found": "Der Ablauf kann nicht fortgesetzt werden, da der aktuelle Knoten fehlt.",
        "error.flow.visit_budget_exhausted": "Der Ablauf hat das sichere Limit für Knotenbesuche überschritten.",
        "error.flow.node_failed": "Ein Ablaufknoten ist fehlgeschlagen und der Lauf wurde beendet.",
        "questionnaire.invalid_object": "Frage {index} muss ein Objekt sein.",
        "questionnaire.invalid_type": "Frage {index} hat einen nicht unterstützten Typ.",
        "questionnaire.missing_title": "Frage {index} benötigt einen Titel.",
        "questionnaire.missing_options": "Frage {index} benötigt mindestens eine Option.",
    },
    "ja": {
        "tool_selection.index_instruction": "ポリシーで許可された追加ツールを、完全なスキーマなしで以下に示します。必要な場合は正確な名前で tool_expand_tools を呼び出し、次のステップで使用してください。",
        "approval.title": "承認が必要です",
        "approval.tool_prompt": "要求されたツール呼び出しを確認してください：{tool}。",
        "approval.guidance": "操作内容とリスクを確認してから次の操作を選んでください。",
        "approval.risk": "この操作はデータまたは外部状態を変更する可能性があります。",
        "recovery.uncertain_tool": "ツールの結果を確認できませんでした。確認方法を選択してください。",
        "recovery.plain_text": "エージェントは複数回応答しましたが、ツールによる進展がありませんでした。",
        "recovery.direction_placeholder": "不足情報を追加するか、別の進め方を指定してください",
        "error.conflict": "この操作は現在の実行状態と競合しています。",
        "error.policy_denied": "有効なセキュリティポリシーにより操作がブロックされました。",
        "error.resource_lost": "必要なランタイムリソースが利用できなくなりました。",
        "error.unsupported_schema": "保存された実行は未対応のデータ形式を使用しています。",
        "error.corrupt_state": "保存された実行状態が不完全または破損しているため、安全に再開できません。",
        "error.uncertain_side_effect": "ツールの実行結果が不明です。続行前に結果を確認してください。",
        "error.cancelled": "操作はキャンセルされました。",
        "error.model.stream_incomplete": "完全な応答を受信する前にモデル接続が終了しました。",
        "error.model.empty_semantic_response": "モデルはトークン生成を報告しましたが、利用可能なテキスト、推論、ツール呼び出しを返しませんでした。Sage が自動再試行しても空の応答が続きました。",
        "error.model.provider_error": "モデルプロバイダーは要求を完了できませんでした。",
        "error.tool.provider_error": "ツールプロバイダーは操作を完了できませんでした。",
        "error.tool.arguments_invalid": "ツール引数が無効です。エージェントは修正して再試行できます。",
        "error.agent.driver_crashed": "エージェントのランタイムが予期せず停止しました。診断情報は記録されています。",
        "error.agent.child_suspended": "委任されたエージェントがユーザー入力を待っています。",
        "error.flow.node_not_found": "現在のノードが存在しないため、ワークフローを続行できません。",
        "error.flow.visit_budget_exhausted": "ワークフローが安全なノード訪問上限を超えました。",
        "error.flow.node_failed": "ワークフローノードが失敗したため、実行を停止しました。",
        "questionnaire.invalid_object": "質問 {index} はオブジェクトである必要があります。",
        "questionnaire.invalid_type": "質問 {index} の形式はサポートされていません。",
        "questionnaire.missing_title": "質問 {index} にはタイトルが必要です。",
        "questionnaire.missing_options": "質問 {index} には少なくとも1つの選択肢が必要です。",
    },
    "ko": {
        "tool_selection.index_instruction": "정책상 허용된 추가 도구가 전체 스키마 없이 아래에 나열됩니다. 필요한 경우 정확한 이름으로 tool_expand_tools를 호출한 뒤 다음 단계에서 사용하세요.",
        "approval.title": "승인이 필요합니다",
        "approval.tool_prompt": "요청된 도구 호출을 확인하세요: {tool}.",
        "approval.guidance": "작업과 위험을 검토한 뒤 다음 작업을 선택하세요.",
        "approval.risk": "이 작업은 데이터 또는 외부 상태를 변경할 수 있습니다.",
        "recovery.uncertain_tool": "도구 결과를 확인할 수 없습니다. 확인 방법을 선택하세요.",
        "recovery.plain_text": "에이전트가 여러 번 응답했지만 도구를 통한 진전이 없었습니다.",
        "recovery.direction_placeholder": "누락된 정보를 추가하거나 다른 진행 방향을 설명하세요",
        "error.conflict": "이 작업은 현재 실행 상태와 충돌합니다.",
        "error.policy_denied": "활성 보안 정책이 작업을 차단했습니다.",
        "error.resource_lost": "필요한 런타임 리소스를 더 이상 사용할 수 없습니다.",
        "error.unsupported_schema": "저장된 실행이 지원되지 않는 데이터 형식을 사용합니다.",
        "error.corrupt_state": "저장된 실행 상태가 불완전하거나 손상되어 안전하게 재개할 수 없습니다.",
        "error.uncertain_side_effect": "도구 실행 결과를 알 수 없습니다. 계속하기 전에 결과를 확인하세요.",
        "error.cancelled": "작업이 취소되었습니다.",
        "error.model.stream_incomplete": "완전한 응답을 받기 전에 모델 연결이 종료되었습니다.",
        "error.model.empty_semantic_response": "모델이 토큰 사용량을 보고했지만 사용 가능한 텍스트, 추론 또는 도구 호출을 반환하지 않았습니다. Sage가 자동으로 다시 시도한 뒤에도 빈 응답이 계속되었습니다.",
        "error.model.provider_error": "모델 공급자가 요청을 완료하지 못했습니다.",
        "error.tool.provider_error": "도구 공급자가 작업을 완료하지 못했습니다.",
        "error.tool.arguments_invalid": "도구 인수가 유효하지 않습니다. 에이전트가 수정한 뒤 다시 시도할 수 있습니다.",
        "error.agent.driver_crashed": "에이전트 런타임이 예기치 않게 중지되었습니다. 진단 정보가 기록되었습니다.",
        "error.agent.child_suspended": "위임된 에이전트가 사용자 입력을 기다리고 있습니다.",
        "error.flow.node_not_found": "현재 노드가 없어 워크플로를 계속할 수 없습니다.",
        "error.flow.visit_budget_exhausted": "워크플로가 안전한 노드 방문 제한을 초과했습니다.",
        "error.flow.node_failed": "워크플로 노드가 실패하여 실행이 중지되었습니다.",
        "questionnaire.invalid_object": "질문 {index}은(는) 객체여야 합니다.",
        "questionnaire.invalid_type": "질문 {index}의 유형은 지원되지 않습니다.",
        "questionnaire.missing_title": "질문 {index}에는 제목이 필요합니다.",
        "questionnaire.missing_options": "질문 {index}에는 옵션이 하나 이상 필요합니다.",
    },
    "ru": {
        "tool_selection.index_instruction": "Ниже перечислены дополнительные разрешённые инструменты без полных схем. Если инструмент нужен, вызовите tool_expand_tools с его точным именем, а затем используйте его на следующем шаге.",
        "approval.title": "Требуется подтверждение",
        "approval.tool_prompt": "Проверьте запрошенный вызов инструмента: {tool}.",
        "approval.guidance": "Перед выбором действия проверьте операцию и связанные риски.",
        "approval.risk": "Эта операция может изменить данные или внешнее состояние.",
        "recovery.uncertain_tool": "Не удалось подтвердить результат инструмента. Выберите способ проверки.",
        "recovery.plain_text": "Агент дал несколько ответов, но не продвинулся с помощью инструментов.",
        "recovery.direction_placeholder": "Добавьте недостающие сведения или укажите другое направление",
        "error.conflict": "Операция конфликтует с текущим состоянием запуска.",
        "error.policy_denied": "Операция заблокирована действующей политикой безопасности.",
        "error.resource_lost": "Необходимый ресурс среды выполнения больше недоступен.",
        "error.unsupported_schema": "Сохранённый запуск использует неподдерживаемый формат данных.",
        "error.corrupt_state": "Сохранённое состояние неполно или повреждено, поэтому его нельзя безопасно возобновить.",
        "error.uncertain_side_effect": "Результат работы инструмента неизвестен. Подтвердите его перед продолжением.",
        "error.cancelled": "Операция отменена.",
        "error.model.stream_incomplete": "Соединение с моделью завершилось до получения полного ответа.",
        "error.model.empty_semantic_response": "Модель сообщила о сгенерированных токенах, но не вернула пригодный текст, рассуждение или вызов инструмента; Sage автоматически повторил запрос, однако снова получил пустой ответ.",
        "error.model.provider_error": "Поставщик модели не смог выполнить запрос.",
        "error.tool.provider_error": "Поставщик инструмента не смог выполнить операцию.",
        "error.tool.arguments_invalid": "Аргументы инструмента недопустимы. Агент может исправить их и повторить попытку.",
        "error.agent.driver_crashed": "Среда выполнения агента неожиданно остановилась. Диагностика сохранена.",
        "error.agent.child_suspended": "Делегированный агент ожидает ответа пользователя.",
        "error.flow.node_not_found": "Процесс не может продолжиться, поскольку текущий узел отсутствует.",
        "error.flow.visit_budget_exhausted": "Процесс превысил безопасный лимит посещений узлов.",
        "error.flow.node_failed": "Узел процесса завершился с ошибкой, и запуск был остановлен.",
        "questionnaire.invalid_object": "Вопрос {index} должен быть объектом.",
        "questionnaire.invalid_type": "Тип вопроса {index} не поддерживается.",
        "questionnaire.missing_title": "Для вопроса {index} требуется заголовок.",
        "questionnaire.missing_options": "Для вопроса {index} требуется хотя бы один вариант.",
    },
}

_MODE_LOCALE_TEXT: dict[str, dict[str, str]] = {
    "pt": {
        "goal.create_instruction": "Esta execução está no modo de objetivo. Antes do trabalho principal, chame goal_submit uma única vez com o objetivo e os critérios de aceitação. A execução só termina após goal_complete.",
        "goal.verify_instruction": "Verifique todos os critérios antes de declarar conclusão. Chame goal_complete somente após a verificação; essa ferramenta é a única porta de conclusão desta execução.",
        "goal.explanation_required": "O objetivo foi registrado como concluído. Na próxima resposta, resuma as entregas, onde encontrá-las ou como usá-las, a verificação realizada e as limitações restantes. Distinga inspeção de código de testes executados; não invente verificações. Fale naturalmente, sem narrar chamadas internas. Não chame goal_complete novamente.",
        "goal.complete_reason": "goal_complete foi concluído e o resultado foi informado.",
        "goal.create_required": "Não há objetivo ativo. Chame goal_submit antes de continuar.",
        "goal.incomplete": "O objetivo ativo ainda não foi concluído. Verifique novamente cada critério e chame goal_complete somente após a validação.",
        "plan.submitted_instruction": "O plano foi aprovado e salvo. Não chame goal_submit novamente; informe brevemente a aprovação antes de encerrar.",
        "plan.explanation_required": "O plano foi aprovado; explique que ele foi salvo antes de encerrar.",
        "plan.submitted_reason": "goal_submit foi concluído após a aprovação do usuário.",
        "plan.required": "O modo de plano não pode terminar diretamente; conclua a investigação e chame goal_submit com o plano completo.",
    },
    "es": {
        "goal.create_instruction": "Esta ejecución está en modo objetivo. Antes del trabajo principal, llama una sola vez a goal_submit con el objetivo y sus criterios de aceptación. La ejecución no puede terminar hasta que goal_complete tenga éxito.",
        "goal.verify_instruction": "Comprueba todos los criterios antes de declarar la finalización. Llama a goal_complete solo después de verificarlos; esa herramienta es la única puerta de finalización.",
        "goal.explanation_required": "El objetivo se registró como completado. En la siguiente respuesta, resume las entregas, dónde encontrarlas o cómo usarlas, la verificación realizada y las limitaciones restantes. Distingue la inspección de código de las pruebas ejecutadas; no inventes verificaciones. Habla con naturalidad, sin narrar llamadas internas. No vuelvas a llamar a goal_complete.",
        "goal.complete_reason": "goal_complete se completó y se informó del resultado.",
        "goal.create_required": "No hay un objetivo activo. Llama a goal_submit antes de continuar.",
        "goal.incomplete": "El objetivo activo no está completo. Revisa cada criterio y llama a goal_complete solo después de verificarlo.",
        "plan.submitted_instruction": "El plan fue aprobado y guardado. No vuelvas a llamar a goal_submit; informa brevemente de la aprobación antes de terminar.",
        "plan.explanation_required": "El plan fue aprobado; explica que se guardó antes de terminar.",
        "plan.submitted_reason": "goal_submit se completó después de la aprobación del usuario.",
        "plan.required": "El modo de plan no puede terminar directamente; completa la investigación y llama a goal_submit con el plan completo.",
    },
    "fr": {
        "goal.create_instruction": "Cette exécution est en mode objectif. Avant le travail principal, appelez goal_submit une seule fois avec l’objectif et ses critères d’acceptation. Elle ne peut se terminer qu’après la réussite de goal_complete.",
        "goal.verify_instruction": "Vérifiez tous les critères avant d’annoncer la fin. Appelez goal_complete uniquement après vérification ; cet outil est l’unique porte de réussite.",
        "goal.explanation_required": "L’objectif est enregistré comme terminé. Dans la prochaine réponse, résumez les livrables, où les trouver ou comment les utiliser, les vérifications réalisées et les limites restantes. Distinguez l’inspection du code des tests exécutés ; n’inventez pas de vérifications. Parlez naturellement sans décrire les appels internes. Ne rappelez pas goal_complete.",
        "goal.complete_reason": "goal_complete a réussi et le résultat a été communiqué.",
        "goal.create_required": "Aucun objectif n’est actif. Appelez goal_submit avant de continuer.",
        "goal.incomplete": "L’objectif actif n’est pas terminé. Revérifiez chaque critère et appelez goal_complete uniquement après validation.",
        "plan.submitted_instruction": "Le plan a été approuvé et enregistré. N’appelez plus goal_submit ; signalez brièvement l’approbation avant de terminer.",
        "plan.explanation_required": "Le plan a été approuvé ; indiquez qu’il a été enregistré avant de terminer.",
        "plan.submitted_reason": "goal_submit a réussi après l’approbation de l’utilisateur.",
        "plan.required": "Le mode plan ne peut pas se terminer directement ; achevez l’analyse et appelez goal_submit avec le plan complet.",
    },
    "de": {
        "goal.create_instruction": "Dieser Lauf befindet sich im Zielmodus. Rufen Sie vor der eigentlichen Arbeit goal_submit genau einmal mit Ziel und Abnahmekriterien auf. Der Lauf endet erst nach erfolgreichem goal_complete.",
        "goal.verify_instruction": "Prüfen Sie alle Kriterien, bevor Sie den Abschluss melden. Rufen Sie goal_complete erst nach der Prüfung auf; dieses Werkzeug ist das einzige Erfolgstor.",
        "goal.explanation_required": "Das Ziel wurde als abgeschlossen erfasst. Fasse in der nächsten Antwort die Ergebnisse, deren Ort oder Verwendung, die tatsächlich durchgeführten Prüfungen und verbleibende Einschränkungen zusammen. Unterscheide Codeprüfung von ausgeführten Tests; erfinde keine Prüfungen. Antworte natürlich, ohne interne Werkzeugaufrufe zu beschreiben. Rufe goal_complete nicht erneut auf.",
        "goal.complete_reason": "goal_complete war erfolgreich und das Ergebnis wurde gemeldet.",
        "goal.create_required": "Es gibt kein aktives Ziel. Rufen Sie vor dem Fortfahren goal_submit auf.",
        "goal.incomplete": "Das aktive Ziel ist noch nicht abgeschlossen. Prüfen Sie jedes Kriterium erneut und rufen Sie goal_complete erst danach auf.",
        "plan.submitted_instruction": "Der Plan wurde genehmigt und gespeichert. Rufen Sie goal_submit nicht erneut auf; melden Sie die Genehmigung kurz vor dem Ende.",
        "plan.explanation_required": "Der Plan wurde genehmigt; erklären Sie vor dem Ende, dass er gespeichert wurde.",
        "plan.submitted_reason": "goal_submit war nach der Genehmigung erfolgreich.",
        "plan.required": "Der Planmodus kann nicht direkt enden; schließen Sie die Untersuchung ab und rufen Sie goal_submit mit dem vollständigen Plan auf.",
    },
    "ja": {
        "goal.create_instruction": "この実行は目標モードです。本作業の前に、具体的な目標と受け入れ条件を指定して goal_submit を一度だけ呼び出してください。goal_complete が成功するまで終了できません。",
        "goal.verify_instruction": "完了を宣言する前に、すべての受け入れ条件を確認してください。検証後にのみ goal_complete を呼び出してください。このツールが唯一の完了ゲートです。",
        "goal.explanation_required": "目標は完了として記録されました。次の返信で、成果物、その場所や使い方、実際に行った検証、残る制限を簡潔にまとめてください。コードの確認と実行したテストを区別し、検証結果を作り上げないでください。内部ツールの呼び出しを実況せず、自然に結果を伝えてください。goal_complete を再度呼び出さないでください。",
        "goal.complete_reason": "goal_complete が成功し、結果が報告されました。",
        "goal.create_required": "有効な目標がありません。続行前に goal_submit を呼び出してください。",
        "goal.incomplete": "有効な目標は未完了です。各受け入れ条件を再確認し、検証後にのみ goal_complete を呼び出してください。",
        "plan.submitted_instruction": "計画は承認され保存されました。goal_submit を再度呼び出さず、終了前に承認結果を簡潔に伝えてください。",
        "plan.explanation_required": "計画は承認されました。終了前に保存済みであることを説明してください。",
        "plan.submitted_reason": "ユーザー承認後に goal_submit が成功しました。",
        "plan.required": "計画モードは直接終了できません。調査を完了し、完全な計画を goal_submit で送信してください。",
    },
    "ko": {
        "goal.create_instruction": "이 실행은 목표 모드입니다. 본 작업 전에 구체적인 목표와 승인 기준으로 goal_submit를 한 번만 호출하세요. goal_complete가 성공해야 종료할 수 있습니다.",
        "goal.verify_instruction": "완료를 선언하기 전에 모든 승인 기준을 확인하세요. 검증 후에만 goal_complete를 호출해야 하며, 이 도구가 유일한 완료 관문입니다.",
        "goal.explanation_required": "목표가 완료로 기록되었습니다. 다음 답변에서 결과물, 위치나 사용법, 실제 검증 내용과 남은 제약을 간결하게 요약하세요. 코드 검토와 실행한 테스트를 구분하고 검증 결과를 지어내지 마세요. 내부 도구 호출을 중계하지 말고 자연스럽게 결과를 설명하세요. goal_complete를 다시 호출하지 마세요.",
        "goal.complete_reason": "goal_complete가 성공했고 결과가 보고되었습니다.",
        "goal.create_required": "활성 목표가 없습니다. 계속하기 전에 goal_submit를 호출하세요.",
        "goal.incomplete": "활성 목표가 아직 완료되지 않았습니다. 각 승인 기준을 다시 확인하고 검증 후에만 goal_complete를 호출하세요.",
        "plan.submitted_instruction": "계획이 승인되어 저장되었습니다. goal_submit을 다시 호출하지 말고 종료 전에 승인 결과를 간단히 알리세요.",
        "plan.explanation_required": "계획이 승인되었습니다. 종료 전에 저장되었다고 설명하세요.",
        "plan.submitted_reason": "사용자 승인 후 goal_submit이 성공했습니다.",
        "plan.required": "계획 모드는 바로 종료할 수 없습니다. 조사를 완료하고 전체 계획으로 goal_submit을 호출하세요.",
    },
    "ru": {
        "goal.create_instruction": "Этот запуск работает в режиме цели. До основной работы один раз вызовите goal_submit с конкретной целью и критериями приёмки. Запуск завершится только после успешного goal_complete.",
        "goal.verify_instruction": "Проверьте все критерии перед заявлением о завершении. Вызывайте goal_complete только после проверки; этот инструмент — единственный шлюз успешного завершения.",
        "goal.explanation_required": "Цель отмечена как выполненная. В следующем ответе кратко опишите результаты, где их найти или как использовать, выполненные проверки и оставшиеся ограничения. Отличайте проверку кода от запущенных тестов; не выдумывайте проверки. Пишите естественно, не описывая внутренние вызовы инструментов. Не вызывайте goal_complete повторно.",
        "goal.complete_reason": "goal_complete выполнен, и результат был сообщён.",
        "goal.create_required": "Активной цели нет. Вызовите goal_submit перед продолжением.",
        "goal.incomplete": "Активная цель ещё не выполнена. Повторно проверьте каждый критерий и вызывайте goal_complete только после проверки.",
        "plan.submitted_instruction": "План одобрен и сохранён. Не вызывайте goal_submit повторно; кратко сообщите об одобрении перед завершением.",
        "plan.explanation_required": "План одобрен; перед завершением сообщите, что он сохранён.",
        "plan.submitted_reason": "goal_submit выполнен после одобрения пользователя.",
        "plan.required": "Режим плана нельзя завершить напрямую; закончите исследование и вызовите goal_submit с полным планом.",
    },
}

for _locale, _values in _COMPLETE_LOCALE_TEXT.items():
    _TRANSLATIONS[_locale].update(_values)
for _locale, _values in _MODE_LOCALE_TEXT.items():
    _TRANSLATIONS[_locale].update(_values)

_TOOL_SELECTION_LOCALE_TEXT = {
    "en": (
        "Select the Tools most useful for the user's current task. Use recent conversation and prior Tool calls. Return only a JSON object whose tools field is an ordered array of exact Tool names.",
        "Select at most {max_tools} Tools.\nRecent conversation:\n{history}\nTool catalog:\n{tools}",
    ),
    "zh": (
        "为用户当前任务选择最有用的工具。结合最近对话和既往工具调用，只返回一个 JSON 对象，其中 tools 字段是按优先级排列的准确工具名称数组。",
        "最多选择 {max_tools} 个工具。\n最近对话：\n{history}\n工具目录：\n{tools}",
    ),
    "pt": (
        "Selecione as ferramentas mais úteis para a tarefa atual do usuário. Use a conversa recente e chamadas anteriores. Retorne apenas um objeto JSON cujo campo tools seja uma lista ordenada de nomes exatos.",
        "Selecione no máximo {max_tools} ferramentas.\nConversa recente:\n{history}\nCatálogo:\n{tools}",
    ),
    "es": (
        "Selecciona las herramientas más útiles para la tarea actual. Usa la conversación reciente y las llamadas anteriores. Devuelve solo un objeto JSON cuyo campo tools sea una lista ordenada de nombres exactos.",
        "Selecciona como máximo {max_tools} herramientas.\nConversación reciente:\n{history}\nCatálogo:\n{tools}",
    ),
    "fr": (
        "Sélectionnez les outils les plus utiles pour la tâche actuelle. Utilisez la conversation récente et les appels précédents. Retournez uniquement un objet JSON dont le champ tools contient les noms exacts par priorité.",
        "Sélectionnez au plus {max_tools} outils.\nConversation récente :\n{history}\nCatalogue :\n{tools}",
    ),
    "de": (
        "Wählen Sie die nützlichsten Werkzeuge für die aktuelle Aufgabe. Berücksichtigen Sie den letzten Dialog und frühere Aufrufe. Geben Sie nur ein JSON-Objekt mit einem geordneten tools-Feld exakter Namen zurück.",
        "Wählen Sie höchstens {max_tools} Werkzeuge.\nLetzter Dialog:\n{history}\nKatalog:\n{tools}",
    ),
    "ja": (
        "現在のユーザータスクに最も役立つツールを選択してください。最近の会話と過去のツール呼び出しを使い、tools フィールドに正確な名前を優先順で並べた JSON オブジェクトだけを返してください。",
        "最大 {max_tools} 個を選択してください。\n最近の会話:\n{history}\nツール一覧:\n{tools}",
    ),
    "ko": (
        "현재 사용자 작업에 가장 유용한 도구를 선택하세요. 최근 대화와 이전 도구 호출을 사용하고, tools 필드에 정확한 이름을 우선순위대로 담은 JSON 객체만 반환하세요.",
        "최대 {max_tools}개를 선택하세요.\n최근 대화:\n{history}\n도구 목록:\n{tools}",
    ),
    "ru": (
        "Выберите наиболее полезные инструменты для текущей задачи. Учитывайте недавний диалог и прошлые вызовы. Верните только JSON-объект, где поле tools содержит точные имена в порядке приоритета.",
        "Выберите не более {max_tools} инструментов.\nНедавний диалог:\n{history}\nКаталог:\n{tools}",
    ),
}
for _locale, (_system, _request) in _TOOL_SELECTION_LOCALE_TEXT.items():
    _TRANSLATIONS[_locale].update(
        {
            "tool_selection.llm_system": _system,
            "tool_selection.llm_request": _request,
        }
    )


def tr(key: str, language: str | None, **params: Any) -> str:
    locale = normalize_language(language)
    localized = _TRANSLATIONS[locale]
    template = localized.get(key)
    if template is None and locale != "en":
        fallback_key = (
            "error.internal"
            if key.startswith("error.")
            else "recovery.guidance"
            if key.startswith("recovery.")
            else "approval.guidance"
            if key.startswith("approval.")
            else "action.submit"
            if key.startswith("action.")
            else "questionnaire.invalid_list"
            if key.startswith("questionnaire.")
            else ""
        )
        template = localized.get(fallback_key)
    template = template or _EN.get(key) or key
    try:
        return template.format(**params)
    except (KeyError, ValueError):
        return template


_ERROR_KEYS = {
    "model.empty_semantic_response": "error.model.empty_semantic_response",
    "model.stream_incomplete": "error.model.stream_incomplete",
    "model.provider_error": "error.model.provider_error",
    "tool.provider_error": "error.tool.provider_error",
    "tool.not_found": "error.tool.not_found",
    "tool.arguments_invalid": "error.tool.arguments_invalid",
    "tool.declined": "error.tool.declined",
    "budget.max_tokens": "error.budget.max_tokens",
    "budget.deadline": "error.budget.deadline",
    "agent.driver_crashed": "error.agent.driver_crashed",
    "agent.child_suspended": "error.agent.child_suspended",
    "flow.node_not_found": "error.flow.node_not_found",
    "flow.visit_budget_exhausted": "error.flow.visit_budget_exhausted",
    "flow.node_failed": "error.flow.node_failed",
}


def localize_error(error: RuntimeErrorInfo, language: str | None) -> RuntimeErrorInfo:
    """Return a safe user-facing error while preserving diagnostics in metadata."""

    locale = normalize_language(language)
    key = error.message_key or _ERROR_KEYS.get(error.code)
    if key is None:
        key = f"error.{error.category.value}"
    params = dict(error.message_params)
    metadata = dict(error.metadata)
    if error.message and error.message != tr(key, locale, **params):
        metadata.setdefault("diagnostic_message", error.message)
    metadata["response_language"] = locale
    return error.model_copy(
        update={
            "message": tr(key, locale, **params),
            "message_key": key,
            "message_params": params,
            "metadata": metadata,
        }
    )


def recovery_payload(
    reason_key: str,
    language: str | None,
    *,
    reason_code: str,
    status: str | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    locale = normalize_language(language)
    params = {"status": status or ""}
    return {
        "title": tr("recovery.title", locale),
        "prompt": tr(reason_key, locale, **params),
        "guidance": tr("recovery.guidance", locale),
        "reason_code": reason_code,
        "message_key": reason_key,
        "message_params": params,
        "language": locale,
        "questions": questions
        or [
            {
                "id": "guidance",
                "type": "text",
                "title": tr("recovery.question", locale),
                "placeholder": tr("recovery.direction_placeholder", locale),
            }
        ],
    }


def error_recovery_payload(
    error: RuntimeErrorInfo,
    language: str | None,
    *,
    resumable: bool,
) -> dict[str, Any]:
    """Build one locale-complete questionnaire for a runtime failure."""

    locale = normalize_language(language)
    options = []
    if resumable:
        options.extend(
            (
                {"label": tr("action.retry", locale), "value": "retry"},
                {
                    "label": tr("action.change_direction", locale),
                    "value": "change_direction",
                },
            )
        )
    options.append({"label": tr("action.cancel", locale), "value": "cancel"})
    questions: list[dict[str, Any]] = [
        {
            "id": "recovery_action",
            "type": "single",
            "title": tr("recovery.question", locale),
            "options": options,
        }
    ]
    if resumable:
        questions.append(
            {
                "id": "guidance",
                "type": "text",
                "title": tr("recovery.input_prompt", locale),
                "placeholder": tr("recovery.direction_placeholder", locale),
            }
        )
    payload = recovery_payload(
        error.message_key or f"error.{error.category.value}",
        locale,
        reason_code=error.code,
        questions=questions,
    )
    payload.update(
        {
            "prompt": error.message,
            "error": error.model_dump(mode="json", exclude_none=True),
            "resumable": resumable,
            "preserve_step_budget": resumable,
        }
    )
    return payload
