from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Freshness = Literal["FRESH", "STALE", "UNKNOWN"]
FuelType = Literal["DIESEL", "PETROL", "OCTANE"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
DecisionAction = Literal["APPROVE", "REJECT", "BLOCK"]
DecisionStatus = Literal["EXECUTED", "REJECTED", "BLOCKED"]


class OperationalSnapshot(BaseModel):
    captured_at: str
    tick: int
    tick_minutes: int = 15
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


class ForecastResult(BaseModel):
    station_id: str
    fuel_type: FuelType
    horizon_ticks: int
    predicted_demand_liters: float
    demand_per_tick: float
    confidence: float
    method: str
    sample_count: int
    per_tick_liters: list[float] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    station_id: str
    fuel_type: FuelType
    risk_level: RiskLevel
    runway_ticks: float | None
    projected_stockout_tick: int | None
    confidence: float
    reason_codes: list[str] = Field(default_factory=list)
    inventory_liters: float
    capacity_liters: float
    inbound_liters: float
    fastest_route_ticks: int | None
    risk_score: float


class ConstraintCheck(BaseModel):
    code: str
    passed: bool
    detail: str


class AllocationAlternative(BaseModel):
    source_depot_id: str
    route_id: str
    quantity: float
    transit_ticks: int
    score: float


class AllocationRecommendation(BaseModel):
    recommendation_id: str
    generated_tick: int
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: FuelType
    quantity: float
    priority: RiskLevel
    confidence: float
    risk_before: float
    risk_after: float
    constraints_checked: bool
    human_review_required: bool = True
    executable: bool
    expected_arrival_tick: int
    expected_runway_after_ticks: float | None
    recommended_action: str
    safe_boundary: str
    reason_codes: list[str] = Field(default_factory=list)
    constraints: list[ConstraintCheck] = Field(default_factory=list)
    alternatives: list[AllocationAlternative] = Field(default_factory=list)


class DecisionSupportBundle(BaseModel):
    generated_at: str
    snapshot_tick: int
    data_freshness: Freshness
    forecasts: list[ForecastResult]
    risks: list[RiskAssessment]
    recommendations: list[AllocationRecommendation]


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DecisionRecord(BaseModel):
    decision_id: str
    recommendation_id: str
    action: DecisionAction
    status: DecisionStatus
    decided_at: str
    decision_tick: int | None = None
    reason: str | None = None
    allocation: dict[str, Any] | None = None
    invalidated_constraints: list[str] = Field(default_factory=list)
