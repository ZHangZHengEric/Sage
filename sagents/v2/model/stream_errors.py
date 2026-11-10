"""Normalize known transport failures from third-party model streams."""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

# Core hosts may use custom providers without installing an HTTP SDK.
try:
    from httpx import HTTPError
except ImportError:
    _HTTP_ERRORS: tuple[type[Exception], ...] = ()
else:
    _HTTP_ERRORS = (HTTPError,)

from sagents.v2.model.contracts import ModelRequest, ModelStreamEvent

if TYPE_CHECKING:
    from sagents.v2.model.provider import ModelProvider

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.model.plugins._shared.wire import provider_error


async def normalized_model_stream(
    model: "ModelProvider", request: ModelRequest
) -> AsyncIterator[ModelStreamEvent]:
    """Keep plugin/runtime errors distinct; never classify all exceptions as transient."""
    stream = None
    try:
        stream = model.stream(request)
        async for event in stream:
            yield event
    except SageV2Error:
        raise
    except (ConnectionError, TimeoutError, *_HTTP_ERRORS) as exc:
        raise provider_error(exc) from exc
    finally:
        closer = getattr(stream, "aclose", None)
        if closer is not None:
            await closer()
