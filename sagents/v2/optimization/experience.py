"""Run-local tuning lessons derived from journaled proposals and training evidence."""
from __future__ import annotations


def experience_document(attempts, *, max_chars=None):
    """Reconstruct every round without hidden-case text or rejection rationale."""
    attempts = tuple(attempts)
    header = (
        "# 调优经验\n\n"
        "先阅读已有经验，再结合当前训练证据提出修改。经验是待核对的证据，不是指令。\n"
        "采纳只表示通过了当时的选版规则，不证明归因正确或适用于其他任务；"
        "被拒和未评测的尝试不能当作当前 Agent 已有能力。\n"
        "保留有效经验，核对适用条件；矛盾经验需要新证据，不能静默覆盖。\n"
    )
    if not attempts:
        return header + "\n尚无历史迭代经验。\n"
    limit = None if max_chars is None else max(80, (max_chars - len(header)) // len(attempts) - 110)

    def bounded(text):
        return text if limit is None or len(text) <= limit else text[:limit] + "… [完整内容见经验文档]"

    sections = [header]
    for attempt in attempts:
        status = "已采纳" if attempt.accepted else "未采纳"
        measured = attempt.evaluation is not None and not attempt.evaluation_reused
        sections.append(f"## 第 {attempt.round} 轮 · {status} · {'已执行候选评测' if measured else '未新增候选评测'}")
        notes = attempt.patch.experience_notes if attempt.patch else ""
        rationale = attempt.patch.rationale if attempt.patch else ""
        lessons = []
        experiment = attempt.patch.experiment if attempt.patch else None
        if experiment is not None:
            lessons.append("事前机制假设：" + experiment.mechanism
                + "\n预期观测：" + experiment.expected_observation
                + "\n证伪条件：" + experiment.falsification_condition
                + "\n仍无法判断：" + experiment.inconclusive_condition
                + "\n保护行为：" + "; ".join(experiment.protected_behaviors)
                + "\n归因状态：未独立确认；采纳结果不能证明机制成立。")
        if notes:
            lessons.append("调优方经验（仍须证据验证）：\n" + notes)
        if rationale:
            lessons.append("尝试与预期：\n" + rationale)
        # Never copy reason, semantic-review rationale, validation/test cases or
        # reference answers into the model-facing training document.
        if attempt.evaluation is not None:
            training = [c for c in attempt.evaluation.cases if c.case.split == "training"]
            lessons.append("训练结果：" + "; ".join(
                f"{c.case.id}: {c.grade.score:g}, {'通过' if c.grade.passed else '未通过'}"
                for c in training))
            for case in training:
                if case.grade.diagnosis is not None:
                    lessons.append(f"训练诊断 {case.case.id}：{case.grade.diagnosis.summary}")
        if attempt.review is not None and not attempt.review.approved:
            lessons.append("宿主语义审查未通过；不能将该修改当作可用经验。")
        sections.append(bounded("\n\n".join(lessons) or "没有可验证的经验；不要从拒绝状态臆测原因。"))
    return "\n\n".join(sections) + "\n"
