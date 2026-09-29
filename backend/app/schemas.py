from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Freshness = Literal["FRESH", "STALE", "UNKNOWN"]


class OperationalSnapshot(BaseModel):
    captured_at: str
    tick: int
    sim_time: str | None = None
    simulation_status: str
    data_freshness: Freshness = "UNKNOWN"
    regions: list[dict[str, Any]] = Field(default_factory=list)
    depots: list[dict[str, Any]] = Field(default_factory=list)
    stations: list[dict[str, Any]] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    supply_arrivals: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    allocations: list[dict[str, Any]] = Field(default_factory=list)
    demand_history: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    degraded_reasons: list[str] = Field(default_factory=list)


class ComponentHealth(BaseModel):
    status: str
    detail: str | None = None


class AppHealth(BaseModel):
    status: str
    backend: ComponentHealth
    simulator: ComponentHealth
    sse: ComponentHealth
    snapshot: ComponentHealth
    tick: int | None = None
    reconnects: int = 0
    events_seen: int = 0
