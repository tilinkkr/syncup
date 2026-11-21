from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

class EquipmentState(BaseModel):
    id: str
    name: str
    status: str  # "OPERATIONAL", "MAINTENANCE_HOLD", "OFFLINE", "DEGRADED"
    telemetry: Dict[str, Any]
    last_serviced: str
    locked_out: bool = False
    active_work_order: Optional[str] = None
    known_issues: List[str] = Field(default_factory=list)

class ShiftRoster(BaseModel):
    shift_id: str
    shift_name: str
    supervisor: str
    active_engineers: List[str]
    permitted_lines: List[str]

class GroundTruthDB(BaseModel):
    plant_name: str = "Industrial Processing Facility Alpha"
    equipment: Dict[str, EquipmentState]
    roster: ShiftRoster
    safety_alerts: List[str]

# Seed operational ground truth context for the industrial SyncUp scenario
INITIAL_GROUND_TRUTH = GroundTruthDB(
    plant_name="Pune Plant 3 - Heavy Engineering & Bottling Zone",
    equipment={
        "BOILER-02": EquipmentState(
            id="BOILER-02",
            name="High-Pressure Steam Boiler #2",
            status="OPERATIONAL",
            telemetry={
                "pressure_bar": 4.1,
                "temp_c": 182.0,
                "vibration_level": "NORMAL",
                "flange_seal_integrity": "OK"
            },
            last_serviced="2026-11-15",
            locked_out=False,
            known_issues=["Minor acoustic buzz reported on bypass manifold (non-critical)"]
        ),
        "LINE-02": EquipmentState(
            id="LINE-02",
            name="High-Speed Bottling & Packaging Line 2",
            status="MAINTENANCE_HOLD",
            telemetry={
                "status": "LOCKED_OUT",
                "power_grid": "ISOLATED",
                "active_work_order": "WO-4482"
            },
            last_serviced="2026-11-19",
            locked_out=True,
            active_work_order="WO-4482: Conveyor motor rewind & sensor calibration",
            known_issues=["Safety lock tag attached. Unsafe to energize before 14:00 IST"]
        ),
        "PUMP-04": EquipmentState(
            id="PUMP-04",
            name="Auxiliary Coolant Pump #4",
            status="OFFLINE",
            telemetry={
                "rpm": 0,
                "flow_rate_lpm": 0.0,
                "bearing_temp_c": 28.0
            },
            last_serviced="2026-10-30",
            locked_out=False,
            known_issues=["Awaiting spare mechanical seal replacement from vendor"]
        ),
        "COOLANT-TANK-03": EquipmentState(
            id="COOLANT-TANK-03",
            name="Central Coolant Reserve Tank #3",
            status="OPERATIONAL",
            telemetry={
                "fill_level_percent": 85.0,
                "ph_level": 7.4
            },
            last_serviced="2026-11-18",
            locked_out=False
        )
    },
    roster=ShiftRoster(
        shift_id="SHIFT-A-MORNING",
        shift_name="Morning Production & Handover (06:00 - 14:00)",
        supervisor="Arun Verma (Senior Shift Lead)",
        active_engineers=[
            "Rajesh Kumar (Mechanical)",
            "Sunil Deshmukh (Electrical)",
            "Vikram Sen (Automation / SCADA)"
        ],
        permitted_lines=["LINE-01", "LINE-03"]
    ),
    safety_alerts=[
        "CRITICAL LOTO: Line 2 is strictly Lockout-Tagout (WO-4482). Under no circumstances should breakers be toggled.",
        "WEAR PPE: Mandatory hard hats and ear protection near Boiler 2 bypass line."
    ]
)
