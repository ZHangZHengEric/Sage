"""Bound local Chromium processes across isolated scorer workers."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import tempfile


@asynccontextmanager
async def browser_slot():
    # Process-owned OS locks are released even if a worker crashes.
    directory = Path(tempfile.gettempdir()) / f'sage-web-design-browsers-{getattr(os, "getuid", lambda: "local")()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    handle = None
    try:
        async with asyncio.timeout(180):
            while handle is None:
                for index in range(4):
                    candidate = (directory / f'{index}.lock').open('a+b')
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            candidate.seek(0)
                            if not candidate.read(1):
                                candidate.write(b'0')
                                candidate.flush()
                            candidate.seek(0)
                            msvcrt.locking(candidate.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except (BlockingIOError, PermissionError):
                        candidate.close()
                        continue
                    except BaseException:
                        candidate.close()
                        raise
                    handle = candidate
                    break
                if handle is None:
                    await asyncio.sleep(.1)
        yield
    finally:
        if handle is not None:
            handle.close()
