"""Explicitly trusted, versioned source extensions using the normal plugin ABI.

These are host extensions, not sandboxed Agent tools. Authorize before loading.
"""
from __future__ import annotations

import sys
import types
import uuid

from sagents.v2.runtime.extensions.contracts import ExtensionRegistration
from sagents.v2.runtime.extensions.discovery import validate_extension_version


class SourcePluginScope:
    def __init__(self):
        self.modules = []

    def load(self, declaration, source):
        code = compile(source, f"extensions/{declaration.id}.py", "exec")
        name = f"_sage_extension_{uuid.uuid4().hex}"
        module = types.ModuleType(name)
        module.__file__ = f"extensions/{declaration.id}.py"
        sys.modules[name] = module
        self.modules.append((name, module))
        exec(code, module.__dict__)
        registration = getattr(module, "registration", None)
        if not isinstance(registration, ExtensionRegistration):
            raise ValueError("source plugin must export an ExtensionRegistration named registration")
        descriptor = registration.descriptor
        if descriptor.plugin_id != declaration.id or descriptor.api_version != "2":
            raise ValueError("source plugin id or API version does not match its declaration")
        if descriptor.built_in:
            raise ValueError("source plugins cannot declare themselves built-in")
        validate_extension_version(registration, declaration.version)
        return registration

    async def close(self):
        for name, module in self.modules:
            if sys.modules.get(name) is module:
                sys.modules.pop(name)
        self.modules.clear()
