"""Local worker-oriented interface for a running GPT Bridge service.

The worker never handles browser captures or login.  It talks only to the
configured local Bridge API and keeps its own small, user-owned state.
"""

from .client import WorkerClient
from .direct import DEFAULT_AGENT_MODEL, DirectWorkerClient, resolve_direct_account
from .storage import WorkerPaths, default_worker_data_dir

__all__ = [
    "DEFAULT_AGENT_MODEL",
    "DirectWorkerClient",
    "WorkerClient",
    "WorkerPaths",
    "default_worker_data_dir",
    "resolve_direct_account",
]
