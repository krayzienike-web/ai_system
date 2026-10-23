from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.auth.api import router as auth_router
from app.core.config import get_settings
from app.core.deps import SessionDep
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

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["system"])
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    api.include_router(auth_router)
    api.include_router(tenancy_router)
    app.include_router(api)
    return app


app = create_app()
