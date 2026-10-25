from backend.routers.health import router as health_router
from backend.routers.auth import router as auth_router
from backend.routers.users import router as users_router
from backend.routers.applications import router as applications_router
from backend.routers.evc import router as evc_router
from backend.routers.documents import router as documents_router
from backend.routers.undertakings import router as undertakings_router

__all__ = [
    "health_router",
    "auth_router",
    "users_router",
    "applications_router",
    "evc_router",
    "documents_router",
    "undertakings_router",
]
