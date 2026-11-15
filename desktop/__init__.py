"""M3 desktop workflow.

The package deliberately keeps the UI thin.  ``M3ProjectService`` is the
versioned service boundary that a future Electron/IPC host can call without
moving media work into a renderer process.
"""

from .models import AudioConflictError, M3ProjectError, ProjectSnapshot
from .service import M3ProjectService

__all__ = [
    "AudioConflictError",
    "M3ProjectError",
    "M3ProjectService",
    "ProjectSnapshot",
]
