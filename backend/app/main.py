from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.auth.api import router as auth_router
from app.core.config import get_settings
from app.core.deps import SessionDep
from app.core.errors import RuleError
from app.experiments.api import router as checks_router
from app.imports.api import router as imports_router
from app.insights.api import router as findings_router
from app.reports.api import router as reports_router
from app.tasks.api import router as tasks_router
from app.tenancy.api import router as tenancy_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Franchise AI Center", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RuleError)
    def rule_error(request: Request, exc: RuleError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["system"])
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    api.include_router(auth_router)
    api.include_router(tenancy_router)
    api.include_router(findings_router)
    api.include_router(tasks_router)
    api.include_router(checks_router)
    api.include_router(reports_router)
    api.include_router(imports_router)
    app.include_router(api)
    return app


app = create_app()
