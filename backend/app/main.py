from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.core.context import client_ip, request_client_id, request_ip_address, request_trace_id
from app.core.errors import ApiError
from app.realtime import hub as realtime_hub
from app.settings import settings

from app.modules.assignments import files as assignment_files
from app.modules.assignments import reviews as assignment_reviews
from app.modules.assignments import router as assignments_router
from app.modules.assignments import submissions as assignment_submissions
from app.modules.assignments import workspace as assignment_workspace
from app.modules.attendance import router as attendance_router
from app.modules.capstone import router as capstone_router
from app.modules.grades import exports as grade_exports
from app.modules.grades import router as grades_router
from app.modules.materials import router as materials_router
from app.modules.members import members as class_members
from app.modules.members import router as members_router
from app.modules.members import teams as member_teams
from app.modules.overview import router as overview_router
from app.modules.system import router as system_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = 80
    await realtime_hub.start()
    try:
        yield
    finally:
        await realtime_hub.stop()


app = FastAPI(title="软件工程作业系统 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
    client_token = request_client_id.set(request.headers.get("X-Client-ID"))
    ip_token = request_ip_address.set(client_ip(request))
    trace_token = request_trace_id.set(request.state.request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    finally:
        request_trace_id.reset(trace_token)
        request_ip_address.reset(ip_token)
        request_client_id.reset(client_token)


@app.exception_handler(ApiError)
async def api_error(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(x) for x in item["loc"] if x != "body"), "message": item["msg"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "提交内容不完整或格式不正确", "details": {"fields": details}, "request_id": request.state.request_id})


# 业务路由按模块注册；顺序与拆分前 main.py 中的定义顺序一致，
# 前端兜底路由必须保持在最后，否则会吃掉所有 API 请求。
app.include_router(system_router.router)
app.include_router(members_router.router)
app.include_router(overview_router.router)
app.include_router(class_members.router)
app.include_router(member_teams.router)
app.include_router(assignments_router.router)
app.include_router(assignment_workspace.router)
app.include_router(materials_router.router)
app.include_router(assignment_files.router)
app.include_router(assignment_submissions.router)
app.include_router(assignment_reviews.router)
app.include_router(grades_router.router)
app.include_router(attendance_router.router)
app.include_router(grade_exports.router)
app.include_router(capstone_router.router)


@app.api_route("/{full_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
def serve_frontend(request: Request, full_path: str):
    if request.method not in {"GET", "HEAD"}:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    dist = settings.frontend_dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    requested = (dist / full_path).resolve()
    if requested.is_relative_to(dist) and requested.is_file():
        if requested == index:
            cache_control = "no-cache"
        elif full_path.startswith("assets/"):
            cache_control = "public, max-age=31536000, immutable"
        else:
            cache_control = "public, max-age=3600"
        return FileResponse(requested, headers={"Cache-Control": cache_control})

    first_segment = full_path.split("/", 1)[0]
    if first_segment in {"api", "health", "assets"} or Path(full_path).suffix:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
