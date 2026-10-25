import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.database import init_db
from backend.routers.health import router as health_router
from backend.routers.auth import router as auth_router
from backend.routers.users import router as users_router
from backend.routers.applications import router as applications_router
from backend.routers.evc import router as evc_router
from backend.routers.documents import router as documents_router
from backend.routers.undertakings import router as undertakings_router
from backend.routers.notifications import router as notifications_router
from backend.routers.admin_time import router as admin_time_router
from backend.background.scheduler import start_scheduler, shutdown_scheduler

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    # Ensure upload directory exists
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    # Initialize database tables
    init_db()
    # Start periodic deadline & SLA escalation background scheduler
    start_scheduler()
    yield
    # Clean shutdown of scheduler
    shutdown_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AICTE Institutional Approval Workflow Automation Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(health_router, prefix=settings.API_V1_PREFIX)
app.include_router(health_router, prefix="/api")  # Convenience alias for /api/health

app.include_router(auth_router, prefix=f"{settings.API_V1_PREFIX}/auth")
app.include_router(auth_router, prefix="/api/auth")  # Required endpoint: POST /api/auth/login

app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(applications_router, prefix=settings.API_V1_PREFIX)
app.include_router(applications_router, prefix="/api")  # Required alias for /api/applications

app.include_router(evc_router, prefix=settings.API_V1_PREFIX)
app.include_router(evc_router, prefix="/api")  # Required alias for /api/evc

app.include_router(documents_router, prefix=settings.API_V1_PREFIX)
app.include_router(documents_router, prefix="/api")

app.include_router(undertakings_router, prefix=settings.API_V1_PREFIX)
app.include_router(undertakings_router, prefix="/api")

app.include_router(notifications_router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications_router, prefix="/api")

app.include_router(admin_time_router, prefix=settings.API_V1_PREFIX)
app.include_router(admin_time_router, prefix="/api")

# Mount static frontend directory
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# Direct Frontend Page Routes
@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    return Response(
        content=b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#127963;&#65039;</text></svg>",
        media_type="image/svg+xml",
    )


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": f"Welcome to {settings.APP_NAME} API"}


@app.get("/login", include_in_schema=False)
async def serve_login():
    login_file = FRONTEND_DIR / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/institution", include_in_schema=False)
async def serve_institution():
    file = FRONTEND_DIR / "institution.html"
    return FileResponse(file) if file.exists() else FileResponse(FRONTEND_DIR / "index.html")


@app.get("/officer", include_in_schema=False)
async def serve_officer():
    file = FRONTEND_DIR / "officer.html"
    return FileResponse(file) if file.exists() else FileResponse(FRONTEND_DIR / "index.html")


@app.get("/bureau", include_in_schema=False)
async def serve_bureau():
    file = FRONTEND_DIR / "bureau.html"
    return FileResponse(file) if file.exists() else FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def serve_admin():
    file = FRONTEND_DIR / "admin.html"
    return FileResponse(file) if file.exists() else FileResponse(FRONTEND_DIR / "index.html")
