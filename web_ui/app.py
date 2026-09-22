from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .command_queue import CommandBusyError
from .core_protocol import CoreProtocol
from .mock_core import InvalidStateError, MockCore
from .schemas import CommandAccepted, Detection, RunRequest, StatusSnapshot

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(*, step_delay: float | None = None) -> FastAPI:
    delay = step_delay
    if delay is None:
        delay = float(os.getenv("SALAD_MOCK_STEP_DELAY", "0.55"))
    core: CoreProtocol = MockCore(step_delay=delay)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await core.shutdown()

    app = FastAPI(
        title="Salad Robot Mock API",
        version="0.1.0",
        description="실제 장비 없이 샐러드 로봇 흐름을 검증하는 Mock API",
        lifespan=lifespan,
    )
    app.state.core = core

    def current_core(request: Request) -> CoreProtocol:
        return request.app.state.core

    def command_error(exc: Exception) -> HTTPException:
        if isinstance(exc, (CommandBusyError, InvalidStateError)):
            return HTTPException(status_code=409, detail=str(exc))
        return HTTPException(status_code=500, detail="명령 처리 중 오류가 발생했습니다.")

    @app.get("/api/status", response_model=StatusSnapshot)
    async def status(request: Request) -> dict[str, Any]:
        return current_core(request).get_status()

    @app.get("/api/detections", response_model=list[Detection])
    async def detections(request: Request) -> list[dict[str, Any]]:
        return current_core(request).get_detections()

    @app.get("/api/logs")
    async def logs(request: Request) -> dict[str, Any]:
        return {"items": current_core(request).get_logs()}

    @app.delete("/api/logs")
    async def clear_logs(request: Request) -> dict[str, bool]:
        current_core(request).clear_logs()
        return {"cleared": True}

    @app.post("/api/initialize", response_model=CommandAccepted, status_code=202)
    async def initialize(request: Request) -> CommandAccepted:
        try:
            job_id = await current_core(request).initialize()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="초기화를 시작했습니다.")

    @app.post("/api/detect", response_model=CommandAccepted, status_code=202)
    async def detect(request: Request) -> CommandAccepted:
        try:
            job_id = await current_core(request).detect_scene()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="장면 인식을 시작했습니다.")

    @app.post("/api/run", response_model=CommandAccepted, status_code=202)
    async def run_salad(payload: RunRequest, request: Request) -> CommandAccepted:
        try:
            job_id = await current_core(request).start_salad(
                payload.recipe, dry_run=payload.dry_run
            )
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="DRY RUN을 시작했습니다.")

    @app.post("/api/stop", response_model=CommandAccepted)
    async def stop(request: Request) -> CommandAccepted:
        await current_core(request).request_stop()
        return CommandAccepted(job_id=None, message="정지를 요청했습니다.")

    @app.post("/api/home", response_model=CommandAccepted, status_code=202)
    async def home(request: Request) -> CommandAccepted:
        try:
            job_id = await current_core(request).move_home()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="준비자세 복귀를 시작했습니다.")

    @app.post("/api/cleanup", response_model=CommandAccepted)
    async def cleanup(request: Request) -> CommandAccepted:
        await current_core(request).cleanup()
        return CommandAccepted(job_id=None, message="Mock 자원을 정리했습니다.")

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await websocket.accept()
        event_queue = core.subscribe()
        try:
            await websocket.send_json({"type": "status", "data": core.get_status()})
            for entry in core.get_logs():
                await websocket.send_json({"type": "log", "data": entry})
            while True:
                event = await event_queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            core.unsubscribe(event_queue)

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
