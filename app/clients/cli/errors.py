from typing import List, Optional

class CLIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        next_steps: Optional[List[str]] = None,
        debug_detail: Optional[str] = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.next_steps = list(next_steps or [])
        self.debug_detail = debug_detail
        self.exit_code = exit_code
