from __future__ import annotations


SIDECAR_PROTOCOL = "sage.runtime/v2"

# Bump this whenever a desktop release cannot safely reuse a sidecar started by
# an older source/build. The Flutter host rejects and retires an incompatible
# registered process before launching the matching backend.
SIDECAR_REVISION = 3
