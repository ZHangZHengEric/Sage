"""Content hashes and typed errors shared by Skill repositories and workspaces."""

from sagents.v2.contracts.skill_payload import files_digest as files_digest
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def skill_error(code: str, message: str, category=ErrorCategory.CONFLICT):
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )

