import logging
import os
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from .schemas import ApiConfig, is_trusted_local_base_url
from .services.app_version import get_app_version
from .services.auth import user_from_token
from .services.config import API_PRESETS
from .services.workbench_store import db_path, workbench_store
from .routers import chat as chat_router
from .routers import config as config_router
from .routers import knowledge as knowledge_router
from .routers import mcp as mcp_router
from .routers import projects as projects_router
from .routers import skills as skills_router
from .routers import themes as themes_router
from .routers import workflows as workflows_router
from .routers.auth import router
from .routers.dependencies import bearer_token

load_dotenv(override=False)

logger = logging.getLogger("standard_ai_workbench.workflow")


def get_cors_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,app://frontend,null")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


LOCAL_FRONTEND_ORIGIN_REGEX = r"^(https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?|app://frontend|null)$"


app = FastAPI(title="Standard AI Workbench Module")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_origin_regex=os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)
app.include_router(router)
app.include_router(projects_router.router)
app.include_router(config_router.router)
app.include_router(themes_router.router)
app.include_router(chat_router.router)
app.include_router(workflows_router.router)
app.include_router(mcp_router.router)
app.include_router(knowledge_router.router)
app.include_router(skills_router.router)


PUBLIC_API_V1_PATHS = {
    "/api/v1/auth/status",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
}


def app_auth_secret_is_valid(request: Request) -> bool:
    expected = os.getenv("APP_AUTH_SECRET", "").strip()
    if not expected:
        return True
    return request.headers.get("x-app-auth-secret", "") == expected


def auth_error_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    origin = request.headers.get("origin")
    origin_is_allowed = origin in get_cors_origins()
    origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", LOCAL_FRONTEND_ORIGIN_REGEX)
    if origin and (origin_is_allowed or re.match(origin_regex, origin)):
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-credentials"] = "true"
        response.headers["access-control-allow-private-network"] = "true"
        response.headers["vary"] = "Origin"
    return response


@app.middleware("http")
async def require_local_auth(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    protected_path = path.startswith("/api/v1/")
    if not protected_path:
        return await call_next(request)

    if not app_auth_secret_is_valid(request):
        return auth_error_response(request, 403, "本机访问密钥无效。")

    if path in PUBLIC_API_V1_PATHS:
        return await call_next(request)

    user = user_from_token(bearer_token(request))
    if user is None:
        return auth_error_response(request, 401, "请先登录。")
    request.state.user = user
    return await call_next(request)


def api_config_from_profile(user_id: str, provider_profile_id: str) -> ApiConfig:
    profile = workbench_store.get_provider_profile(user_id, provider_profile_id)
    api_key = workbench_store.resolve_api_key(user_id, provider_profile_id)
    if not api_key and not is_trusted_local_base_url(profile.base_url):
        raise ValueError("请先配置 API key。")
    return ApiConfig(provider=profile.provider, base_url=profile.base_url, api_key=api_key, model=profile.model)


@app.on_event("startup")
def startup() -> None:
    workbench_store.prune_expired_auth_sessions()


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "standard-ai-workbench-module",
        "version": get_app_version(),
        "database": str(db_path()),
        "presets": API_PRESETS,
    }
