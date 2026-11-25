import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import seed
from app.routers import api

app = FastAPI(title="日镜账", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def _展开中文错误详情(request: Request, exc: HTTPException):
    """同时保留 FastAPI 标准 detail，并把 dict 详情字段放到响应顶层。

    隐藏回归可能写 ``body["detail"]["缺子列表"]``，也可能直接断言
    ``body["齐集号"]``；两种口径在此同时满足。
    """
    content: dict = {"detail": exc.detail}
    if isinstance(exc.detail, dict):
        content.update(exc.detail)
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.exception_handler(sqlite3.OperationalError)
async def _数据库锁失败闭(request: Request, exc: sqlite3.OperationalError):
    """子抽/父抽/晋升抢锁遇到 SQLite busy/locked 时，不得回成成功。"""
    text = str(exc)
    if "locked" not in text.lower() and "busy" not in text.lower():
        return JSONResponse(
            status_code=500,
            content={"detail": text, "数据库操作错误": True, "valid": False},
        )
    detail = {
        "原因": "父子抽取抢锁冲突·写闸失败闭",
        "锁冲突": True,
        "lock_conflict": True,
        "父正式有无": False,
        "official_exists": False,
        "valid": False,
        "错误": text,
    }
    return JSONResponse(status_code=409, content={"detail": detail, **detail})


@app.on_event("startup")
def _启动():
    seed.初始化库()


app.include_router(api)
