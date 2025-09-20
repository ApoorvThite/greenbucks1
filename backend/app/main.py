from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings, AppInfo
from .api.routes.health import router as health_router
from .api.routes.users import router as users_router
from .api.routes.plaid import router as plaid_router
from .api.routes.transactions import router as transactions_router
from .api.routes.auth import router as auth_router
from .api.routes.receipts import router as receipts_router
from .api.routes.plaid_webhook import router as plaid_webhook_router

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import timedelta
from .db.session import SessionLocal
from .services.plaid_service import sync_all_items


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize resources here if needed (DB connections, clients, etc.)
    settings = get_settings()
    app.state.settings = settings

    # APScheduler: run Plaid sync every 30 minutes
    scheduler = AsyncIOScheduler()

    def _scheduled_sync_job():
        try:
            with SessionLocal() as db:
                total = sync_all_items(db)
                print(f"[scheduler] Plaid sync completed, upserted {total} transactions")
        except Exception as e:
            print(f"[scheduler] Plaid sync failed: {e}")

    scheduler.add_job(_scheduled_sync_job, "interval", minutes=30, id="plaid_sync_interval", replace_existing=True)
    scheduler.start()
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        # Cleanup resources here if needed
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    # CORS (adjust origins for your frontend URL)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    application.include_router(health_router, prefix="", tags=["health"]) 
    application.include_router(users_router)
    application.include_router(plaid_router)
    application.include_router(transactions_router)
    application.include_router(auth_router)
    application.include_router(receipts_router)
    application.include_router(plaid_webhook_router)

    # Inject OpenAPI security scheme so Swagger shows the Authorize button
    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        openapi_schema = get_openapi(
            title=application.title,
            version=application.version,
            description="GreenBucks API",
            routes=application.routes,
        )
        security_scheme = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "bearerAuth"
        ] = security_scheme
        # Set a global security requirement so the Authorize button applies broadly
        openapi_schema["security"] = [{"bearerAuth": []}]
        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore

    @application.get("/")
    async def root():
        settings_local = get_settings()
        return {
            "message": "Welcome to GreenBucks API",
            "app": AppInfo(
                name=settings_local.app_name,
                environment=settings_local.environment,
                version=application.version,
            ).model_dump(),
        }

    return application


app = create_app()
