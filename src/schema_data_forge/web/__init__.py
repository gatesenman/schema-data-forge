"""Web UI (FastAPI backend plus static browser frontend)."""

from .server import app, create_app, serve

__all__ = ["app", "create_app", "serve"]
