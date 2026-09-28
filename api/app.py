"""FastAPI 应用入口。启动命令：uvicorn api.app:app --reload"""

from __future__ import annotations

import os
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes.chat import router as chat_router
from api.routes.demo import router as demo_router
from api.routes.pmc import health_router, router as pmc_router
from api.schemas.errors import PublicErrorResponse


logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    """从环境变量读取逗号分隔的本地前端地址；绝不默认允许全部来源。"""
    configured = os.getenv("PMC_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("PMC_ALLOWED_ORIGINS 不允许使用 '*'，请配置明确 origin")
    return origins


app = FastAPI(
    title="PMC-Agent API",
    version="1.0.0-alpha",
    description="基于确定性 LangGraph PMC 工作流的本地 HTTP API。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _public_error_for_status(status_code: int) -> PublicErrorResponse:
    """将 HTTP 异常统一为演示页面可直接展示的中文提示。"""
    if status_code == 404:
        return PublicErrorResponse(
            code="SESSION_EXPIRED",
            user_message="当前演示会话已失效，请重新开始分析。",
        )
    if status_code == 409:
        return PublicErrorResponse(
            code="SESSION_UNAVAILABLE",
            user_message="当前演示会话暂时无法继续，请重新开始分析。",
        )
    if status_code == 422:
        return PublicErrorResponse(
            code="INVALID_REQUEST",
            user_message="请输入完整且有效的生产任务后重试。",
        )
    if status_code >= 500:
        return PublicErrorResponse(
            code="ANALYSIS_UNAVAILABLE",
            user_message="分析服务暂时异常，请稍后重试。",
        )
    return PublicErrorResponse(
        code="REQUEST_FAILED",
        user_message="当前请求暂时无法处理，请稍后重试。",
    )


@app.exception_handler(HTTPException)
async def public_http_exception_handler(_: Request, error: HTTPException) -> JSONResponse:
    """绝不把路由 detail 直接返回给演示客户端。"""
    public_error = _public_error_for_status(error.status_code)
    return JSONResponse(status_code=error.status_code, content=public_error.model_dump())


@app.exception_handler(RequestValidationError)
async def public_validation_exception_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    """隐藏 Pydantic 字段细节，仅记录可诊断日志。"""
    logger.info("API 请求校验失败：%s", error.errors())
    public_error = _public_error_for_status(422)
    return JSONResponse(status_code=422, content=public_error.model_dump())


@app.exception_handler(Exception)
async def public_unhandled_exception_handler(_: Request, error: Exception) -> JSONResponse:
    """内部错误记录到日志，客户端仅获得稳定提示。"""
    logger.exception("未处理的 API 异常", exc_info=error)
    public_error = _public_error_for_status(500)
    return JSONResponse(status_code=500, content=public_error.model_dump())

app.include_router(health_router)
app.include_router(pmc_router)
app.include_router(chat_router)
app.include_router(demo_router)
