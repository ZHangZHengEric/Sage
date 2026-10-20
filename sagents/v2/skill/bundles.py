"""Content hashes and typed errors shared by Skill repositories and workspaces."""

import hashlib

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def files_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def skill_error(code: str, message: str, category=ErrorCategory.CONFLICT):
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=message,
            safe_to_resume=True,
        )
    )

