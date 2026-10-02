"""Pure calculation and operations logic for FermentOps.

Every function in this module is deterministic and free of side effects: no
I/O, no global state, and no reading of the system clock (callers pass ``now``
explicitly). Canonical units are litres, kilograms, grams, degrees Fahrenheit
and specific gravity (SG). Invalid inputs raise :class:`FermentValueError`.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from schemas import (
    SG_MAX,
    SG_MIN,
    TEMP_MAX_F,
    TEMP_MIN_F,
    Batch,
    Stage,
    UnitSystem,
)

# --- Constants ---------------------------------------------------------------
ABV_FACTOR: float = 131.25
DEFAULT_CAL_TEMP_F: float = 60.0

# Water-density temperature-correction polynomial coefficients (T in degF).
_C0: float = 1.00130346
_C1: float = 0.000134722124
_C2: float = 0.00000204052596
_C3: float = 0.00000000232820948

# Brix / SG / sugar-mass relationship used for sugar additions.
SG_PER_BRIX: float = 0.004  # 1 Brix ~= 1.004 SG
GRAMS_PER_LITRE_PER_BRIX: float = 10.4

# Mass multiplier relative to sucrose needed to deliver the same gravity.
# Dextrose monohydrate (corn sugar) contributes ~42 vs 46 gravity points.
SUGAR_FACTORS: Dict[str, float] = {
    "Sucrose": 1.0,
    "Dextrose": 46.0 / 42.0,
}

LITRES_PER_GALLON: float = 3.785411784
KG_PER_LB: float = 0.45359237
G_PER_OZ: float = 28.349523125

# Acceptable fermentation temperature window per stage (degrees F).
STAGE_TEMP_RANGE_F: Dict[Stage, Tuple[float, float]] = {
    Stage.PRIMARY: (59.0, 77.0),
    Stage.SECONDARY: (59.0, 77.0),
    Stage.COLD_CRASH: (30.0, 45.0),
    Stage.AGING: (50.0, 68.0),
}


class FermentValueError(ValueError):
    """Raised when a calculation receives an invalid or unsafe input."""


# --- Validation helpers ------------------------------------------------------
def _require_finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FermentValueError(f"{name} must be a finite number")


def _require_sg(name: str, value: float) -> None:
    _require_finite(name, value)
    if not SG_MIN <= value <= SG_MAX:
        raise FermentValueError(
            f"{name} must be between {SG_MIN:.3f} and {SG_MAX:.3f} "
            f"(got {value:.4f})"
        )


def _require_temp_f(name: str, value: float) -> None:
    _require_finite(name, value)
    if not TEMP_MIN_F <= value <= TEMP_MAX_F:
        raise FermentValueError(
            f"{name} must be between {TEMP_MIN_F:.0f} and "
            f"{TEMP_MAX_F:.0f} degF (got {value:.1f})"
        )


def _require_positive(name: str, value: float) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise FermentValueError(f"{name} must be greater than zero")


# --- Unit conversion ---------------------------------------------------------
def f_to_c(temp_f: float) -> float:
    """Convert degrees Fahrenheit to Celsius."""
    return (temp_f - 32.0) * 5.0 / 9.0


def c_to_f(temp_c: float) -> float:
    """Convert degrees Celsius to Fahrenheit."""
    return temp_c * 9.0 / 5.0 + 32.0


def litres_to_gallons(litres: float) -> float:
    """Convert litres to US gallons."""
    return litres / LITRES_PER_GALLON


def gallons_to_litres(gallons: float) -> float:
    """Convert US gallons to litres."""
    return gallons * LITRES_PER_GALLON


def kg_to_lb(kg: float) -> float:
    """Convert kilograms to pounds."""
    return kg / KG_PER_LB


def lb_to_kg(lb: float) -> float:
    """Convert pounds to kilograms."""
    return lb * KG_PER_LB


def grams_to_oz(grams: float) -> float:
    """Convert grams to avoirdupois ounces."""
    return grams / G_PER_OZ


def temp_to_display(temp_f: float, units: UnitSystem) -> float:
    """Convert a canonical degF value to the display unit system."""
    return temp_f if units is UnitSystem.IMPERIAL else f_to_c(temp_f)


def temp_from_display(value: float, units: UnitSystem) -> float:
    """Convert a displayed temperature back to canonical degF."""
    return value if units is UnitSystem.IMPERIAL else c_to_f(value)


def volume_to_display(litres: float, units: UnitSystem) -> float:
    """Convert canonical litres to the display unit system."""
    return litres if units is UnitSystem.METRIC else litres_to_gallons(litres)


def volume_from_display(value: float, units: UnitSystem) -> float:
    """Convert a displayed volume back to canonical litres."""
    return value if units is UnitSystem.METRIC else gallons_to_litres(value)


def weight_to_display(kg: float, units: UnitSystem) -> float:
    """Convert canonical kilograms to the display unit system."""
    return kg if units is UnitSystem.METRIC else kg_to_lb(kg)


def weight_from_display(value: float, units: UnitSystem) -> float:
    """Convert a displayed weight back to canonical kilograms."""
    return value if units is UnitSystem.METRIC else lb_to_kg(value)


def unit_labels(units: UnitSystem) -> Dict[str, str]:
    """Return display labels for temperature, volume and weight."""
    if units is UnitSystem.METRIC:
        return {"temp": "°C", "volume": "L", "weight": "kg", "small": "g"}
    return {"temp": "°F", "volume": "gal", "weight": "lb", "small": "oz"}


# --- 1. Hydrometer temperature correction ------------------------------------
def _density_polynomial(temp_f: float) -> float:
    """Evaluate the water-density correction polynomial at ``temp_f``."""
    return (
        _C0
        - _C1 * temp_f
        + _C2 * temp_f**2
        - _C3 * temp_f**3
    )


def correct_hydrometer_reading(
    sg_measured: float,
    temp_measured_f: float,
    temp_calibration_f: float = DEFAULT_CAL_TEMP_F,
) -> float:
    """Temperature-correct a hydrometer reading.

    ``SG_corr = SG_meas * P(T_meas) / P(T_cal)`` where ``P`` is the cubic
    water-density polynomial in degrees Fahrenheit.

    Args:
        sg_measured: Raw specific gravity read from the hydrometer.
        temp_measured_f: Sample temperature in degF.
        temp_calibration_f: Temperature the hydrometer is calibrated for.

    Returns:
        The corrected specific gravity.

    Raises:
        FermentValueError: On out-of-range inputs or a degenerate
            (non-positive) calibration polynomial value.
    """
    _require_sg("Measured SG", sg_measured)
    _require_temp_f("Measured temperature", temp_measured_f)
    _require_temp_f("Calibration temperature", temp_calibration_f)

    denominator = _density_polynomial(temp_calibration_f)
    if denominator <= 0:
        raise FermentValueError("Calibration polynomial is non-positive")
    return sg_measured * _density_polynomial(temp_measured_f) / denominator


# --- 2. ABV and fermentation metrics -----------------------------------------
def potential_abv(sg_start: float, sg_final: float) -> float:
    """Return standard ABV (%) = ``(SG_start - SG_final) * 131.25``.

    Raises:
        FermentValueError: If either SG is out of range or the final
            gravity is above the starting gravity.
    """
    _require_sg("Starting SG", sg_start)
    _require_sg("Final SG", sg_final)
    if sg_final > sg_start:
        raise FermentValueError("Final SG cannot exceed starting SG")
    return (sg_start - sg_final) * ABV_FACTOR


def attenuation_rate(sg_start: float, sg_final: float) -> float:
    """Return apparent attenuation (%).

    ``(SG_start - SG_final) / (SG_start - 1.000) * 100``

    Raises:
        FermentValueError: If SGs are out of range, the final gravity is
            above the start, or the start is 1.000 (division by zero).
    """
    _require_sg("Starting SG", sg_start)
    _require_sg("Final SG", sg_final)
    if sg_final > sg_start:
        raise FermentValueError("Final SG cannot exceed starting SG")
    denominator = sg_start - 1.000
    if denominator <= 1e-9:
        raise FermentValueError(
            "Starting SG must be above 1.000 to compute attenuation"
        )
    return (sg_start - sg_final) / denominator * 100.0


@dataclass(frozen=True)
class SugarAdditionResult:
    """Outcome of a sugar-boost calculation."""

    sugar_g: float
    grams_per_litre: float
    brix_increase: float
    gravity_points_added: float
    abv_gain: float
    sugar_type: str


def sugar_addition(
    volume_l: float,
    sg_start: float,
    sg_target: float,
    sugar_type: str = "Sucrose",
) -> SugarAdditionResult:
    """Compute sugar mass needed to raise ``volume_l`` from start to target SG.

    Uses ``1 Brix ~= 0.004 SG`` and ``1 Brix ~= 10.4 g/L``::

        brix_increase = (SG_target - SG_start) / 0.004
        sugar_g       = brix_increase * 10.4 * V * type_factor

    Dextrose is scaled by ``46/42`` because it yields fewer gravity points
    per gram than sucrose. Volume displacement by the added sugar is ignored.

    Raises:
        FermentValueError: On invalid volume, SG range, a target at or below
            the start gravity, or an unknown sugar type.
    """
    _require_positive("Volume", volume_l)
    _require_sg("Starting SG", sg_start)
    _require_sg("Target SG", sg_target)
    if sg_target <= sg_start:
        raise FermentValueError("Target SG must be above starting SG")
    if sugar_type not in SUGAR_FACTORS:
        raise FermentValueError(
            f"Unknown sugar type '{sugar_type}'; "
            f"choose from {sorted(SUGAR_FACTORS)}"
        )

    brix_increase = (sg_target - sg_start) / SG_PER_BRIX
    grams_per_litre = (
        brix_increase * GRAMS_PER_LITRE_PER_BRIX * SUGAR_FACTORS[sugar_type]
    )
    return SugarAdditionResult(
        sugar_g=grams_per_litre * volume_l,
        grams_per_litre=grams_per_litre,
        brix_increase=brix_increase,
        gravity_points_added=(sg_target - sg_start) * 1000.0,
        abv_gain=(sg_target - sg_start) * ABV_FACTOR,
        sugar_type=sugar_type,
    )


# --- 3. Dehydrator wet-to-dry yield ------------------------------------------
@dataclass(frozen=True)
class DehydratorResult:
    """Outcome of a dehydrator wet-to-dry calculation (all weights in kg)."""

    wet_kg: float
    dry_kg: float
    water_removed_kg: float
    wet_per_tray_kg: float
    dry_per_tray_kg: float
    final_moisture_pct: float
    yield_pct: float
    trays: int


def dehydrator_yield(
    wet_weight_kg: float,
    moisture_reduction_pct: float,
    trays: int,
    initial_moisture_pct: float = 85.0,
) -> DehydratorResult:
    """Estimate dry yield and per-tray loading for a dehydrator batch.

    ``moisture_reduction_pct`` is the share of the *initial wet mass* that is
    removed as water, so ``dry = wet * (1 - reduction / 100)``. The final
    moisture content of the dried product is::

        (initial_moisture - reduction) / (100 - reduction) * 100

    Args:
        wet_weight_kg: Initial wet pulp/fruit weight in kg.
        moisture_reduction_pct: Percent of wet mass removed, in (0, 100).
        trays: Number of trays used (>= 1).
        initial_moisture_pct: Water content of the fresh material, in
            [0, 100). Removal cannot exceed it.

    Raises:
        FermentValueError: On non-positive weight/trays, out-of-range
            percentages, or removal exceeding the available water.
    """
    _require_positive("Wet weight", wet_weight_kg)
    _require_finite("Moisture reduction", moisture_reduction_pct)
    _require_finite("Initial moisture", initial_moisture_pct)
    if not isinstance(trays, int) or isinstance(trays, bool) or trays < 1:
        raise FermentValueError("Number of trays must be a whole number >= 1")
    if not 0 <= initial_moisture_pct < 100:
        raise FermentValueError("Initial moisture must be in [0, 100)")
    if not 0 < moisture_reduction_pct < 100:
        raise FermentValueError("Moisture reduction must be in (0, 100)")
    if moisture_reduction_pct > initial_moisture_pct:
        raise FermentValueError(
            "Moisture reduction cannot exceed the initial moisture content "
            f"({initial_moisture_pct:.1f}%)"
        )

    dry_kg = wet_weight_kg * (1.0 - moisture_reduction_pct / 100.0)
    final_moisture = (
        (initial_moisture_pct - moisture_reduction_pct)
        / (100.0 - moisture_reduction_pct)
        * 100.0
    )
    return DehydratorResult(
        wet_kg=wet_weight_kg,
        dry_kg=dry_kg,
        water_removed_kg=wet_weight_kg - dry_kg,
        wet_per_tray_kg=wet_weight_kg / trays,
        dry_per_tray_kg=dry_kg / trays,
        final_moisture_pct=final_moisture,
        yield_pct=dry_kg / wet_weight_kg * 100.0,
        trays=trays,
    )


# --- Batch tracking ----------------------------------------------------------
@dataclass(frozen=True)
class BatchProgress:
    """Timeline progress of a batch at a point in time."""

    days_elapsed: float
    days_total: int
    fraction: float
    overdue: bool


def batch_progress(batch: Batch, now: datetime) -> BatchProgress:
    """Compute timeline progress for ``batch`` at time ``now``.

    ``fraction`` is clamped to [0, 1]; ``overdue`` flags an elapsed time
    beyond the expected duration.
    """
    elapsed = max((now - batch.start_date).total_seconds() / 86400.0, 0.0)
    total = batch.expected_duration_days
    return BatchProgress(
        days_elapsed=elapsed,
        days_total=total,
        fraction=min(elapsed / total, 1.0),
        overdue=elapsed > total,
    )


def evaluate_alerts(batch: Batch, now: datetime) -> List[str]:
    """Return human-readable alerts for a batch (empty list if healthy).

    Rules:
        * Temperature outside the stage's recommended window.
        * Primary fermentation with a silent airlock while gravity is still
          well above target (possible stuck ferment).
        * No airlock reading logged in the last 24 hours during Primary.
        * Batch past its expected duration.
    """
    alerts: List[str] = []
    progress = batch_progress(batch, now)

    if batch.current_temp_f is not None:
        low, high = STAGE_TEMP_RANGE_F[batch.stage]
        if not low <= batch.current_temp_f <= high:
            alerts.append(
                f"Temperature {batch.current_temp_f:.1f}°F is outside the "
                f"{batch.stage.value} window ({low:.0f}-{high:.0f}°F)"
            )

    if batch.stage is Stage.PRIMARY:
        rate = batch.latest_bubble_rate
        if batch.bubble_log:
            last_ts = max(r.timestamp for r in batch.bubble_log)
            if (now - last_ts).total_seconds() > 86400:
                alerts.append("No airlock reading in the last 24 hours")
        elif progress.days_elapsed >= 1:
            alerts.append("No airlock readings logged yet")

        gravity_high = (
            batch.current_gravity is not None
            and batch.target_final_gravity is not None
            and batch.current_gravity - batch.target_final_gravity > 0.004
        )
        if (
            rate is not None
            and rate < 1.0
            and progress.days_elapsed >= 2
            and gravity_high
        ):
            alerts.append(
                "Airlock silent while gravity is above target: "
                "possible stuck fermentation"
            )

    if progress.overdue:
        alerts.append(
            f"Past expected duration ({progress.days_total} days)"
        )
    return alerts


def current_metrics(batch: Batch) -> Dict[str, Optional[float]]:
    """Return ABV and attenuation for a batch, ``None`` where undefined."""
    if batch.current_gravity is None:
        return {"abv": None, "attenuation": None}
    try:
        return {
            "abv": potential_abv(
                batch.original_gravity, batch.current_gravity
            ),
            "attenuation": attenuation_rate(
                batch.original_gravity, batch.current_gravity
            ),
        }
    except FermentValueError:
        return {"abv": None, "attenuation": None}


# --- Markdown production sheet -----------------------------------------------
def _fmt(value: Optional[float], spec: str, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:{spec}}{suffix}"


def render_production_sheet(
    batches: Sequence[Batch],
    units: UnitSystem,
    generated_at: datetime,
    include_gravity_log: bool = True,
    include_activity_log: bool = True,
    include_alerts: bool = True,
) -> str:
    """Compile batches into a Markdown production sheet.

    Raises:
        FermentValueError: If no batches are supplied.
    """
    if not batches:
        raise FermentValueError("Select at least one batch to export")

    labels = unit_labels(units)
    vol_u, temp_u = labels["volume"], labels["temp"]
    lines: List[str] = [
        "# FermentOps Production Sheet",
        "",
        f"- **Generated:** {generated_at:%Y-%m-%d %H:%M}",
        f"- **Units:** {units.value}",
        f"- **Batches:** {len(batches)}",
        "",
        "## Summary",
        "",
        f"| ID | Name | Stage | Day | Volume ({vol_u}) | OG | Current SG "
        "| ABV % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in batches:
        prog = batch_progress(b, generated_at)
        m = current_metrics(b)
        lines.append(
            f"| {b.batch_id} | {b.name} | {b.stage.value} "
            f"| {prog.days_elapsed:.1f}/{prog.days_total} "
            f"| {volume_to_display(b.volume_l, units):.1f} "
            f"| {b.original_gravity:.3f} "
            f"| {_fmt(b.current_gravity, '.3f')} | {_fmt(m['abv'], '.1f')} |"
        )

    for b in batches:
        prog = batch_progress(b, generated_at)
        m = current_metrics(b)
        temp = (
            None
            if b.current_temp_f is None
            else temp_to_display(b.current_temp_f, units)
        )
        lines += [
            "",
            "---",
            "",
            f"## {b.batch_id} - {b.name}",
            "",
            f"- **Product:** {b.product}",
            f"- **Stage:** {b.stage.value}",
            f"- **Started:** {b.start_date:%Y-%m-%d}",
            f"- **Progress:** {prog.days_elapsed:.1f} of "
            f"{prog.days_total} days ({prog.fraction:.0%})",
            f"- **Volume:** {volume_to_display(b.volume_l, units):.2f} "
            f"{vol_u}",
            f"- **Original gravity:** {b.original_gravity:.3f}",
            f"- **Current gravity:** {_fmt(b.current_gravity, '.3f')}",
            f"- **Target final gravity:** "
            f"{_fmt(b.target_final_gravity, '.3f')}",
            f"- **Potential ABV:** {_fmt(m['abv'], '.2f', '%')}",
            f"- **Apparent attenuation:** "
            f"{_fmt(m['attenuation'], '.1f', '%')}",
            f"- **Temperature:** {_fmt(temp, '.1f', ' ' + temp_u)}",
            f"- **Latest airlock rate:** "
            f"{_fmt(b.latest_bubble_rate, '.1f', ' bubbles/min')}",
        ]
        if include_alerts:
            alerts = evaluate_alerts(b, generated_at)
            lines += ["", "**Alerts**", ""]
            lines += [f"- WARNING: {a}" for a in alerts] or ["- None"]
        if include_gravity_log and b.gravity_log:
            lines += [
                "",
                "**Gravity log**",
                "",
                f"| Time | Measured | Temp ({temp_u}) | Corrected |",
                "|---|---|---|---|",
            ]
            for g in sorted(b.gravity_log, key=lambda r: r.timestamp):
                lines.append(
                    f"| {g.timestamp:%Y-%m-%d %H:%M} | {g.sg_measured:.3f} "
                    f"| {temp_to_display(g.temp_f, units):.1f} "
                    f"| {_fmt(g.sg_corrected, '.4f')} |"
                )
        if include_activity_log and b.log:
            lines += ["", "**Activity log**", ""]
            for e in sorted(b.log, key=lambda r: r.timestamp):
                lines.append(
                    f"- {e.timestamp:%Y-%m-%d %H:%M} **{e.kind.value}**: "
                    f"{e.message}"
                )
        if b.notes:
            lines += ["", f"> {b.notes}"]

    lines.append("")
    return "\n".join(lines)
