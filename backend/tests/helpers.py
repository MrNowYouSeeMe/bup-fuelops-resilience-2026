from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.schemas import OperationalSnapshot


FUELS = ("DIESEL", "PETROL", "OCTANE")


def base_snapshot(
    *,
    tick: int = 32,
    freshness: str = "FRESH",
    with_history: bool = True,
) -> OperationalSnapshot:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sim_time = start + timedelta(minutes=15 * tick)

    regions = [
        {"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.0},
        {"id": "region-chattogram", "name": "Chattogram Division", "demand_factor": 1.08},
    ]
    depots = [
        {
            "id": "depot-gazipur",
            "name": "Gazipur Depot",
            "region_id": "region-dhaka",
            "status": "OPEN",
            "dispatch_capacity_per_tick": 12000,
            "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000},
            "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
        },
        {
            "id": "depot-patiya",
            "name": "Patiya Depot",
            "region_id": "region-chattogram",
            "status": "OPEN",
            "dispatch_capacity_per_tick": 11000,
            "capacity": {"DIESEL": 85000, "PETROL": 65000, "OCTANE": 40000},
            "inventory": {"DIESEL": 55000, "PETROL": 42000, "OCTANE": 24000},
        },
    ]
    stations = [
        {
            "id": "station-mirpur",
            "name": "Mirpur Fuel Station",
            "region_id": "region-dhaka",
            "status": "OPEN",
            "demand_profile": "urban_high",
            "demand_multiplier": 1.0,
            "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
            "inventory": {"DIESEL": 4500, "PETROL": 3900, "OCTANE": 2400},
        },
        {
            "id": "station-tongi",
            "name": "Tongi Industrial Fuel Station",
            "region_id": "region-dhaka",
            "status": "OPEN",
            "demand_profile": "industrial",
            "demand_multiplier": 1.0,
            "capacity": {"DIESEL": 18000, "PETROL": 9000, "OCTANE": 6000},
            "inventory": {"DIESEL": 4200, "PETROL": 3300, "OCTANE": 2200},
        },
        {
            "id": "station-karnaphuli",
            "name": "Karnaphuli Highway Station",
            "region_id": "region-chattogram",
            "status": "OPEN",
            "demand_profile": "highway",
            "demand_multiplier": 1.0,
            "capacity": {"DIESEL": 14000, "PETROL": 15000, "OCTANE": 9000},
            "inventory": {"DIESEL": 4300, "PETROL": 4700, "OCTANE": 2600},
        },
        {
            "id": "station-coxsbazar",
            "name": "Cox's Bazar Regional Station",
            "region_id": "region-chattogram",
            "status": "OPEN",
            "demand_profile": "regional",
            "demand_multiplier": 1.0,
            "capacity": {"DIESEL": 12000, "PETROL": 12000, "OCTANE": 7000},
            "inventory": {"DIESEL": 3600, "PETROL": 3700, "OCTANE": 2100},
        },
    ]
    routes = [
        {
            "id": "route-gazipur-mirpur",
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-mirpur",
            "transit_ticks": 2,
            "max_shipment": 7000,
            "status": "AVAILABLE",
        },
        {
            "id": "route-gazipur-tongi",
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-tongi",
            "transit_ticks": 2,
            "max_shipment": 6500,
            "status": "AVAILABLE",
        },
        {
            "id": "route-patiya-karnaphuli",
            "source_depot_id": "depot-patiya",
            "destination_station_id": "station-karnaphuli",
            "transit_ticks": 2,
            "max_shipment": 7000,
            "status": "AVAILABLE",
        },
        {
            "id": "route-patiya-coxsbazar",
            "source_depot_id": "depot-patiya",
            "destination_station_id": "station-coxsbazar",
            "transit_ticks": 3,
            "max_shipment": 6000,
            "status": "AVAILABLE",
        },
        {
            "id": "route-gazipur-karnaphuli",
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-karnaphuli",
            "transit_ticks": 4,
            "max_shipment": 5000,
            "status": "AVAILABLE",
        },
        {
            "id": "route-patiya-mirpur",
            "source_depot_id": "depot-patiya",
            "destination_station_id": "station-mirpur",
            "transit_ticks": 4,
            "max_shipment": 5000,
            "status": "AVAILABLE",
        },
    ]

    history = []
    if with_history:
        base = {
            "urban_high": {"DIESEL": 110, "PETROL": 135, "OCTANE": 72},
            "industrial": {"DIESEL": 150, "PETROL": 50, "OCTANE": 25},
            "highway": {"DIESEL": 120, "PETROL": 125, "OCTANE": 70},
            "regional": {"DIESEL": 85, "PETROL": 90, "OCTANE": 42},
        }
        by_id = {s["id"]: s for s in stations}
        row_id = 1
        for t in range(max(0, tick - 15), tick + 1):
            at = start + timedelta(minutes=15 * t)
            for station_id, station in by_id.items():
                for fuel in FUELS:
                    demand = float(base[station["demand_profile"]][fuel]) * (1.0 + ((t % 3) - 1) * 0.03)
                    history.append(
                        {
                            "id": row_id,
                            "station_id": station_id,
                            "fuel_type": fuel,
                            "tick": t,
                            "sim_time": at.isoformat(),
                            "demand_liters": round(demand, 3),
                            "served_liters": round(demand, 3),
                            "unmet_liters": 0.0,
                        }
                    )
                    row_id += 1

    return OperationalSnapshot(
        captured_at=datetime.now(timezone.utc).isoformat(),
        tick=tick,
        tick_minutes=15,
        sim_time=sim_time.isoformat(),
        simulation_status="PAUSED",
        data_freshness=freshness,
        regions=deepcopy(regions),
        depots=deepcopy(depots),
        stations=deepcopy(stations),
        routes=deepcopy(routes),
        supply_arrivals=[],
        events=[],
        allocations=[],
        demand_history=history,
        metrics={
            "served_demand_liters": 10000.0,
            "unmet_demand_liters": 0.0,
            "service_level": 1.0,
            "allocation_liters": 0.0,
            "allocation_failures": 0,
        },
        degraded_reasons=[] if freshness == "FRESH" else ["SIMULATOR_STALE_DATA"],
    )
