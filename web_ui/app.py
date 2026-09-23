from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from .command_queue import CommandBusyError
from .core_protocol import CoreProtocol
from .mock_core import InvalidStateError, MockCore
from .schemas import CommandAccepted, Detection, RunRequest, StatusSnapshot, DetectRequest

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(*, step_delay: float | None = None, core=None) -> FastAPI:
    delay = step_delay
    if delay is None:
        delay = float(os.getenv("SALAD_MOCK_STEP_DELAY", "0.55"))
    if core is None:
        mode = os.getenv('SALAD_CORE','mock').lower()
        if mode == 'real':
            from .real_core import RealCore
            core = RealCore()
        elif mode == 'mock':
            core = MockCore(step_delay=delay)
        else:
            raise ValueError('SALAD_CORE는 mock 또는 real이어야 합니다.')

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await core.shutdown()

    app = FastAPI(
        title="Salad Robot API",
        version="0.2.0",
        description="Mock / 실제 장비 05~09 실행 API",
        lifespan=lifespan,
    )
    app.state.core = core

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method in ('POST','DELETE') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'다른 출처의 제어 요청을 허용하지 않습니다.'},status_code=403)
        return await call_next(request)

    def is_real():
        return bool(core.get_status()['live_robot'])

    def current_core(request: Request) -> CoreProtocol:
        return request.app.state.core

    def command_error(exc: Exception) -> HTTPException:
        if isinstance(exc, (CommandBusyError, InvalidStateError, ValueError)):
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
    async def detect(request: Request, payload: DetectRequest | None = None) -> CommandAccepted:
        try:
            if is_real():
                job_id = await core.detect_scene(rotate=bool(payload and payload.rotate))
            else:
                job_id = await core.detect_scene()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="장면 인식을 시작했습니다.")

    @app.post("/api/run", response_model=CommandAccepted, status_code=202)
    async def run_salad(payload: RunRequest, request: Request) -> CommandAccepted:
        try:
            if is_real():
                job_id = await core.execute_command('salad',payload)
            else:
                job_id = await core.start_salad(payload.recipe,dry_run=payload.dry_run)
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="계획 검증을 시작했습니다." if payload.dry_run else "전체 실행 요청을 접수했습니다.")

    @app.post('/api/test/{kind}', response_model=CommandAccepted, status_code=202)
    async def test_command(kind: str, payload: RunRequest):
        if kind not in ('bowl-hover','pick-hover','pick','pick-place','return'):
            raise HTTPException(404,'없는 시험입니다.')
        if not is_real():
            raise HTTPException(409,'단계별 장비 시험은 REAL 모드에서 제공합니다. Mock은 DRY RUN을 사용하세요.')
        try:
            job_id = await core.execute_command(kind,payload)
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id,message='시험 요청을 접수했습니다.')

    @app.get('/api/scene-image')
    async def scene_image():
        picture = getattr(core,'picture',None)
        if picture is None: raise HTTPException(404,'촬영된 사진이 없습니다.')
        return Response(content=picture,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.post("/api/stop", response_model=CommandAccepted)
    async def stop(request: Request) -> CommandAccepted:
        await current_core(request).request_stop()
        return CommandAccepted(job_id=None, message="정지를 요청했습니다.")

    @app.post("/api/home", response_model=CommandAccepted, status_code=202)
    async def home(request: Request, payload: RunRequest | None = None) -> CommandAccepted:
        try:
            job_id = (await core.execute_command('home',payload or RunRequest())) if is_real() else await core.move_home()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=job_id, message="준비자세 복귀를 시작했습니다.")

    @app.post("/api/cleanup", response_model=CommandAccepted)
    async def cleanup(request: Request) -> CommandAccepted:
        try:
            await current_core(request).cleanup()
        except Exception as exc:
            raise command_error(exc) from exc
        return CommandAccepted(job_id=None, message="정리를 완료했습니다.")

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        await websocket.accept()
        event_queue = core.subscribe()
        try:
            await websocket.send_json({"type": "status", "data": core.get_status()})
            await websocket.send_json({'type':'detections','data':{'items':core.get_detections()}})
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
