from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class SystemState(str, Enum):
    OFFLINE = "OFFLINE"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    OBSERVING = "OBSERVING"
    TARGET_SELECTED = "TARGET_SELECTED"
    APPROACHING = "APPROACHING"
    GRASPING = "GRASPING"
    TRANSFERRING = "TRANSFERRING"
    RELEASING = "RELEASING"
    POURING = "POURING"
    HOMING = "HOMING"
    STOPPING = "STOPPING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"
    HOLDING = "HOLDING"


class CommandAccepted(BaseModel):
    accepted: bool = True
    job_id: str | None = None
    message: str


class RunRequest(BaseModel):
    recipe: dict[str, int] = Field(
        default_factory=lambda: {"tomato": 1, "cheese": 1, "berry": 1}
    )
    dry_run: bool = True
    confirmation: str = ""
    scene_id: str | None = None
    rotate: bool = False
    reference_yaw_deg: float | None = Field(default=None, allow_inf_nan=False)
    hover_height_mm: float = Field(default=100, ge=50, le=150, allow_inf_nan=False)
    vel: float = Field(default=10, ge=1, le=20, allow_inf_nan=False)
    acc: float = Field(default=10, ge=1, le=20, allow_inf_nan=False)
    class_name: Literal['tomato','cheese','berry'] = 'tomato'


class DetectRequest(BaseModel):
    rotate: bool = False


class Detection(BaseModel):
    id: str
    class_name: str
    display_name: str
    confidence: float
    pixel: list[int]
    angle_deg: float | None = None
    depth_m: float | None = None
    base_mm: list[float]
    box: list[int]
    valid: bool = True
    reason: str | None = None
    status: str = "대기"


class StatusSnapshot(BaseModel):
    state: SystemState
    robot_connected: bool
    camera_connected: bool
    model_loaded: bool
    live_robot: bool = False
    mode: str = "DRY_RUN"
    busy: bool
    active_job_id: str | None
    current_step: str | None
    progress: int
    last_error: str | None
    updated_at: str
    gripper_connected: bool = False
    tcp: str | None = None
    scene_id: str | None = None
    scene_valid: bool = False
    image_available: bool = False
    recovery_required: bool = False
    restart_required: bool = False
    camera_profile: dict[str, int] | None = None


class EventMessage(BaseModel):
    type: str
    data: dict[str, Any]
