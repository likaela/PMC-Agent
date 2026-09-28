"""FastAPI 应用入口。启动命令：uvicorn api.app:app --reload"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.chat import router as chat_router
from api.routes.pmc import health_router, router as pmc_router
from api.routes.scenario import router as scenario_router


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
app.include_router(health_router)
app.include_router(pmc_router)
app.include_router(chat_router)
app.include_router(scenario_router)
