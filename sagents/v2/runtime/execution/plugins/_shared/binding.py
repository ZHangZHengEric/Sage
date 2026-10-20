"""Errors shared by concrete execution binding plugins."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def incompatible_configuration(message):
    return SageV2Error(RuntimeErrorInfo(
        code="execution.configuration_incompatible", category=ErrorCategory.VALIDATION,
        message=message, message_key="error.execution.configuration_incompatible",
        message_params={"reason": message}, safe_to_resume=False,
    ))
