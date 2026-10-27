import contextlib
import logging
import multiprocessing
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .planner import DinnerRequest, demo_plan, retained_recipe
from .errors import AgentFailure, classify_failure

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
app = FastAPI(title="冰箱有招", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
app.mount("/static", StaticFiles(directory=ROOT / "fridge" / "static"), name="static")
_agent_lock = threading.Lock()
logger = logging.getLogger(__name__)


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get("host"):
            return JSONResponse({"detail": "仅接受本地页面的同源请求。"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "fridge" / "static" / "index.html")


@app.get("/api/status")
def status():
    from .agent import model_ready
    return {"model_ready": model_ready(), "version": "0.1.0-preview"}


def _worker(payload: dict, connection):
    # Contain hangs and suppress provider errors/logs that could include secrets.
    # A process timeout is NOT a security sandbox; see README execution boundaries.
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            from .agent import run_agent
            result = run_agent(DinnerRequest(**payload))
        connection.send((True, result))
    except Exception as exc:
        failure = classify_failure(exc)
        # Outside redirected stderr: only a fixed category and bounded counters.
        logger.warning("Agent worker failed: code=%s counts=%s", failure.code, failure.diagnostics)
        connection.send((False, failure.code))
    finally:
        connection.close()


def isolated_agent(payload: dict, timeout: float = 90):
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_worker, args=(payload, sender), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise TimeoutError("本次任务超过 90 秒，已停止。请重试或切换示例体验。")
        try:
            success, result = receiver.recv()
        except (EOFError, OSError):
            raise AgentFailure("worker_stopped") from None
        if not success:
            raise AgentFailure(result)
        return result
    finally:
        receiver.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if not process.is_alive():
            process.close()


@app.post("/api/plan")
def plan(request: DinnerRequest):
    try:
        retained_recipe(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if request.mode == "demo":
        try:
            return demo_plan(request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    from .agent import model_ready
    if not model_ready():
        raise HTTPException(409, "模型尚未配置。请填写本地 .env 后重启，或先用示例体验。")
    if not _agent_lock.acquire(blocking=False):
        raise HTTPException(429, "已有一个 Agent 任务正在运行，请稍后重试。")
    try:
        return isolated_agent(request.model_dump())
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from None
    except Exception as exc:
        failure = classify_failure(exc)
        logger.warning("Agent task failed: code=%s", failure.code)
        raise HTTPException(failure.status_code,
                            {"message": failure.message, "code": failure.code}) from None
    finally:
        _agent_lock.release()
