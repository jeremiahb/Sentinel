"""Shared entity models used by agent and cloud services."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Endpoint(BaseModel):
    id: str
    hostname: str
    os_platform: Literal["windows", "macos", "ios", "android"]
    os_version: str
    mdm_platform: Literal["intune", "jamf"]
    mdm_device_id: str
    status: Literal["provisioning", "active", "offline", "retired"] = "provisioning"
    last_heartbeat: datetime | None = None


class PolicyEvent(BaseModel):
    id: str | None = None
    mdm_platform: str = "intune"
    external_id: str
    policy_name: str
    policy_type: str
    target_groups: list[str] = Field(default_factory=list)
    deployed_by: str | None = None
    deployed_at: datetime
    raw_payload: dict = Field(default_factory=dict)


class Run(BaseModel):
    id: str
    endpoint_id: str
    trigger_type: Literal["policy_event", "manual", "scheduled"]
    status: Literal["queued", "running", "complete", "timed_out", "failed"] = "queued"
    aggregate_result: Literal["pass", "fail", "degraded"] | None = None
