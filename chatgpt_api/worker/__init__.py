"""Local worker-oriented interface for a running GPT Bridge service.

The worker never handles browser captures or login.  It talks only to the
configured local Bridge API and keeps its own small, user-owned state.
"""

from .client import WorkerClient
from .storage import WorkerPaths, default_worker_data_dir

__all__ = ["WorkerClient", "WorkerPaths", "default_worker_data_dir"]
