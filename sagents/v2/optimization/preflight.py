"""Source-aware semantic admission, separate from deterministic dataset validation."""
from sagents.v2.optimization.contracts import OptimizationSuite


class GeneratedCasesRejected(ValueError):
    def __init__(self, review):
        self.review = review
        super().__init__('Generated drafts could not be admitted after bounded repair')


async def admit_cases(cases, *, generated, schema, policy, review_case_set, repair,
                      emit, round=0, event_name='suite_review_completed'):
    current = schema(cases=tuple(cases))
    for attempt in range(policy.generated_repairs + 1):
        review = await review_case_set(current)
        known = {case.id for case in current.cases}
        unknown = sorted(set().union(*(set(issue.case_ids) for issue in review.issues)) - known)
        emit(event_name, round=round, attempt=attempt,
            disposition="admitted" if review.approved else "repair_required" if generated else "diagnostic_only",
            source="generated" if generated else "imported", review=review.model_dump(mode="json"),
            unresolved_case_ids=unknown)
        if (review.approved and not unknown) or not generated:
            return current, review
        if attempt < policy.generated_repairs:
            repaired = await repair(current, review)
            if {(case.id, case.split) for case in repaired.cases} != {(case.id, case.split) for case in current.cases}:
                raise ValueError("generated repair changed case identity or split")
            emit("generated_cases_repaired", round=round, attempt=attempt + 1,
                before=current.model_dump(mode="json"), after=repaired.model_dump(mode="json"))
            current = repaired
        else:
            rejected = set().union(*(set(issue.case_ids) for issue in review.issues if issue.severity == "blocking"))
            rejected &= known
            if not rejected:
                rejected = known
            emit("generated_cases_quarantined", round=round,
                cases=[case.model_dump(mode="json") for case in current.cases if case.id in rejected],
                review=review.model_dump(mode="json"), reason="semantic_repair_exhausted")
            retained = tuple(case for case in current.cases if case.id not in rejected)
            # Required dev cases cannot disappear from a generated experiment's denominator.
            if (not retained or any(case.split in {"validation", "test", "final"} and case.id in rejected for case in current.cases)):
                if schema is OptimizationSuite:
                    raise GeneratedCasesRejected(review)
                return None, review
            try:
                return schema(cases=retained), review
            except ValueError:
                raise GeneratedCasesRejected(review) from None

