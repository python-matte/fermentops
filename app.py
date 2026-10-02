"""FermentOps: micro-batch fermentation management dashboard (Streamlit UI)."""

from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional, TypeVar

import pandas as pd
import streamlit as st
from pydantic import ValidationError

import core_logic as cl
import storage
from schemas import (
    TEMP_MAX_F,
    TEMP_MIN_F,
    Batch,
    BubbleReading,
    ExportOptions,
    GravityReading,
    LogEntry,
    LogKind,
    Stage,
    UnitSystem,
)

T = TypeVar("T")

STAGE_EMOJI: Dict[Stage, str] = {
    Stage.PRIMARY: "🟢",
    Stage.SECONDARY: "🟠",
    Stage.COLD_CRASH: "🔵",
    Stage.AGING: "🟣",
}
STAGE_BADGE_COLOR: Dict[Stage, str] = {
    Stage.PRIMARY: "green",
    Stage.SECONDARY: "orange",
    Stage.COLD_CRASH: "blue",
    Stage.AGING: "violet",
}

METRIC_CSS = """
<style>
div[data-testid="stMetricValue"] { font-size: 2.1rem; font-weight: 700; }
div[data-testid="stMetricLabel"] p { font-weight: 600; opacity: 0.8; }
</style>
"""


# --- Seed data & state -------------------------------------------------------
def _bubbles(now: datetime, rates: List[float]) -> List[BubbleReading]:
    """Build bubble readings spaced 8 h apart, newest 2 h ago."""
    n = len(rates)
    return [
        BubbleReading(
            timestamp=now - timedelta(hours=2 + 8 * (n - 1 - i)),
            bubbles_per_minute=rate,
        )
        for i, rate in enumerate(rates)
    ]


def _seed_batches(now: datetime) -> List[Batch]:
    """Create the active demo batches."""
    return [
        Batch(
            batch_id="FB-001",
            name="Isabella Grape Wine",
            product="Wine",
            volume_l=3.0,
            start_date=now - timedelta(days=6),
            stage=Stage.PRIMARY,
            expected_duration_days=21,
            original_gravity=1.090,
            target_final_gravity=0.996,
            current_gravity=1.044,
            current_temp_f=70.0,
            bubble_log=_bubbles(now, [12, 24, 36, 41, 35, 28]),
            gravity_log=[
                GravityReading(
                    timestamp=now - timedelta(days=3),
                    sg_measured=1.068,
                    temp_f=70.0,
                    sg_corrected=1.0686,
                ),
            ],
            log=[
                LogEntry(
                    timestamp=now - timedelta(days=6),
                    kind=LogKind.ADDITION,
                    message="Crushed Isabella grapes, pitched yeast with "
                    "nutrients.",
                ),
            ],
            notes="Punch down the cap twice daily during primary.",
        ),
        Batch(
            batch_id="FB-002",
            name="Dry Apple Cider",
            product="Cider",
            volume_l=23.0,
            start_date=now - timedelta(days=16),
            stage=Stage.SECONDARY,
            expected_duration_days=28,
            original_gravity=1.054,
            target_final_gravity=1.006,
            current_gravity=1.008,
            current_temp_f=66.0,
            bubble_log=_bubbles(now, [9, 7, 5, 3, 2]),
            log=[
                LogEntry(
                    timestamp=now - timedelta(days=9),
                    kind=LogKind.TRANSFER,
                    message="Racked off lees into secondary carboy.",
                ),
            ],
        ),
        Batch(
            batch_id="FB-003",
            name="Melon Kombucha",
            product="Kombucha",
            volume_l=8.0,
            start_date=now - timedelta(days=9),
            stage=Stage.SECONDARY,
            expected_duration_days=14,
            original_gravity=1.030,
            target_final_gravity=1.008,
            current_gravity=1.014,
            current_temp_f=74.0,
            log=[
                LogEntry(
                    timestamp=now - timedelta(days=3),
                    kind=LogKind.ADDITION,
                    message="Started second fermentation with melon puree.",
                ),
            ],
            notes="Burp bottles daily during second fermentation.",
        ),
        Batch(
            batch_id="FB-004",
            name="Grape Kombucha",
            product="Kombucha",
            volume_l=8.0,
            start_date=now - timedelta(days=8),
            stage=Stage.SECONDARY,
            expected_duration_days=14,
            original_gravity=1.030,
            target_final_gravity=1.008,
            current_gravity=1.016,
            current_temp_f=74.0,
            log=[
                LogEntry(
                    timestamp=now - timedelta(days=2),
                    kind=LogKind.ADDITION,
                    message="Started second fermentation with grape juice.",
                ),
            ],
        ),
    ]


@st.cache_resource
def _store() -> storage.Store:
    """The process-wide batch store (SQLite file, or demo no-op store)."""
    return storage.make_store()


def _save(batch: Batch) -> None:
    _store().save_batch(batch)


def _init_state() -> None:
    """Load batches for a new session, seeding the demo set on first use."""
    if "batches" not in st.session_state:
        store = _store()
        seed = _seed_batches(datetime.now())
        if not store.persistent:
            st.session_state["batches"] = seed
        else:
            if not store.is_seeded():
                for batch in seed:
                    store.save_batch(batch)
                store.mark_seeded()
            st.session_state["batches"] = store.load_batches()
    st.session_state.setdefault("sheet_md", None)
    st.session_state.setdefault("sheet_name", None)


def _batches() -> List[Batch]:
    return st.session_state["batches"]


def _find_batch(batch_id: str) -> Batch:
    for batch in _batches():
        if batch.batch_id == batch_id:
            return batch
    raise KeyError(batch_id)


def _flash(kind: str, message: str) -> None:
    """Queue a message to display on the next render (used by callbacks)."""
    st.session_state["flash"] = (kind, message)


def _show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        {"error": st.error, "success": st.success}.get(kind, st.info)(
            message
        )


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )


def _safe(fn: Callable[..., T], *args: object) -> Optional[T]:
    """Run a calculation, rendering any validation failure inline."""
    try:
        return fn(*args)
    except cl.FermentValueError as exc:
        st.error(str(exc))
        return None


def _temp_bounds(units: UnitSystem) -> Dict[str, float]:
    return {
        "min_value": round(cl.temp_to_display(TEMP_MIN_F, units), 1),
        "max_value": round(cl.temp_to_display(TEMP_MAX_F, units), 1),
    }


# --- Sidebar -----------------------------------------------------------------
def render_sidebar(now: datetime) -> UnitSystem:
    """Render the sidebar and return the active unit system."""
    st.sidebar.title("🍾 FermentOps")
    st.sidebar.caption("Micro-batch fermentation management")
    if _store().persistent:
        st.sidebar.caption("💾 Readings are saved to a local database.")
    else:
        st.sidebar.caption(
            "🧪 Demo mode: your changes are private to this tab and "
            "reset on refresh."
        )

    units = UnitSystem(
        st.sidebar.radio(
            "Units",
            [u.value for u in UnitSystem],
            horizontal=True,
            help="Metric: °C, L, kg, g.  Imperial: °F, gal, lb, oz.",
        )
    )

    batches = _batches()
    if batches:
        ids = [b.batch_id for b in batches]
        st.sidebar.selectbox(
            "Active batch",
            ids,
            key="selected_batch_id",
            format_func=lambda i: f"{i} · {_find_batch(i).name}",
        )
    else:
        st.sidebar.info("No batches yet. Add one in the tracker tab.")

    alerts = {
        b.batch_id: cl.evaluate_alerts(b, now) for b in batches
    }
    flagged = {k: v for k, v in alerts.items() if v}
    st.sidebar.metric(
        "Active ferment alerts",
        sum(len(v) for v in flagged.values()),
        delta=f"{len(flagged)} of {len(batches)} batches",
        delta_color="inverse" if flagged else "off",
    )
    if flagged:
        with st.sidebar.expander("View alerts", expanded=False):
            for batch_id, items in flagged.items():
                st.markdown(f"**{batch_id} · {_find_batch(batch_id).name}**")
                for item in items:
                    st.markdown(f"- {item}")
    else:
        st.sidebar.success("All ferments nominal")
    return units


# --- Tab 1: Precision calculators --------------------------------------------
def _panel_hydrometer(units: UnitSystem) -> None:
    labels = cl.unit_labels(units)
    st.subheader("Hydrometer correction")
    tkw = _temp_bounds(units)
    sg_meas = st.number_input(
        "Measured SG", 0.980, 1.200, 1.050, 0.001, format="%.3f",
        key="hc_sg",
    )
    t_meas = st.number_input(
        f"Sample temperature ({labels['temp']})",
        value=round(cl.temp_to_display(77.0, units), 1),
        step=0.5, key=f"hc_tmeas_{units.value}", **tkw,
    )
    t_cal = st.number_input(
        f"Hydrometer calibration temp ({labels['temp']})",
        value=round(cl.temp_to_display(cl.DEFAULT_CAL_TEMP_F, units), 1),
        step=0.5, key=f"hc_tcal_{units.value}", **tkw,
        help="Most hydrometers are calibrated at 60°F (15.6°C) or "
        "68°F (20°C); check the stem.",
    )
    corrected = _safe(
        cl.correct_hydrometer_reading,
        sg_meas,
        cl.temp_from_display(t_meas, units),
        cl.temp_from_display(t_cal, units),
    )
    if corrected is not None:
        with st.container(border=True):
            st.metric(
                "Corrected SG",
                f"{corrected:.4f}",
                delta=f"{corrected - sg_meas:+.4f} vs measured",
                delta_color="off",
            )


def _panel_sugar(units: UnitSystem) -> None:
    labels = cl.unit_labels(units)
    st.subheader("Sugar boost")
    default_vol = 3.0 if units is UnitSystem.METRIC else 0.8
    volume = st.number_input(
        f"Batch volume ({labels['volume']})", 0.1, 10000.0, default_vol,
        0.25, key=f"sb_vol_{units.value}",
    )
    sg_start = st.number_input(
        "Starting SG", 0.980, 1.200, 1.050, 0.001, format="%.3f",
        key="sb_start",
    )
    sg_target = st.number_input(
        "Target SG", 0.980, 1.200, 1.090, 0.001, format="%.3f",
        key="sb_target",
    )
    result = _safe(
        cl.sugar_addition,
        cl.volume_from_display(volume, units),
        sg_start,
        sg_target,
        "Sucrose",
    )
    if result is not None:
        if units is UnitSystem.METRIC:
            headline = f"{result.sugar_g:,.0f} g"
            alt = f"{result.sugar_g / 1000:.2f} kg"
        else:
            oz = cl.grams_to_oz(result.sugar_g)
            headline = f"{oz:,.1f} oz"
            alt = f"{oz / 16:.2f} lb"
        with st.container(border=True):
            st.metric("White sugar to add", headline, delta=alt,
                      delta_color="off")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.metric("Brix gain", f"+{result.brix_increase:.1f}°Bx")
            c2.metric("ABV gain", f"+{result.abv_gain:.2f}%")


def _panel_dehydrator(units: UnitSystem) -> None:
    labels = cl.unit_labels(units)
    st.subheader("Dehydrator yield")
    default_w = 5.0 if units is UnitSystem.METRIC else 10.0
    wet = st.number_input(
        f"Wet pulp / fruit weight ({labels['weight']})", 0.01, 1000.0,
        default_w, 0.1, key=f"dh_wet_{units.value}",
    )
    initial = st.number_input(
        "Initial moisture content (%)", 0.0, 99.0, 85.0, 1.0,
        key="dh_init",
    )
    reduction = st.number_input(
        "Target moisture reduction (% of wet weight)", 0.1, 99.0, 75.0, 1.0,
        key="dh_red",
        help="Share of the initial wet mass removed as water.",
    )
    trays = int(
        st.number_input("Available trays", 1, 100, 6, 1, key="dh_trays")
    )
    result = _safe(
        cl.dehydrator_yield,
        cl.weight_from_display(wet, units),
        reduction,
        trays,
        initial,
    )
    if result is not None:
        w = labels["weight"]

        def disp(kg: float) -> float:
            return cl.weight_to_display(kg, units)

        with st.container(border=True):
            st.metric(
                "Expected dry yield",
                f"{disp(result.dry_kg):.2f} {w}",
                delta=f"{result.yield_pct:.1f}% of wet weight",
                delta_color="off",
            )
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.metric("Wet / tray",
                      f"{disp(result.wet_per_tray_kg):.2f} {w}")
            c2.metric("Dry / tray",
                      f"{disp(result.dry_per_tray_kg):.2f} {w}")
        st.caption(
            f"Water removed: {disp(result.water_removed_kg):.2f} {w} · "
            f"final moisture ≈ {result.final_moisture_pct:.1f}%"
        )
        tray_df = pd.DataFrame(
            {
                "Tray": range(1, trays + 1),
                f"Wet load ({w})": round(disp(result.wet_per_tray_kg), 3),
                f"Dry yield ({w})": round(disp(result.dry_per_tray_kg), 3),
            }
        )
        with st.expander("Per-tray distribution"):
            st.dataframe(tray_df, hide_index=True, width="stretch")


def _panel_abv() -> None:
    st.subheader("ABV & attenuation")
    inputs, outputs = st.columns([1, 2])
    with inputs:
        og = st.number_input(
            "Starting SG (OG)", 0.980, 1.200, 1.090, 0.001, format="%.3f",
            key="abv_og",
        )
        fg = st.number_input(
            "Final SG (FG)", 0.980, 1.200, 1.010, 0.001, format="%.3f",
            key="abv_fg",
        )
    with outputs:
        abv = _safe(cl.potential_abv, og, fg)
        att = _safe(cl.attenuation_rate, og, fg)
        if abv is not None and att is not None:
            c1, c2, c3 = st.columns(3)
            with c1.container(border=True):
                st.metric("Potential ABV", f"{abv:.2f}%")
            with c2.container(border=True):
                st.metric("Attenuation", f"{att:.1f}%")
            with c3.container(border=True):
                st.metric("Gravity drop", f"{(og - fg) * 1000:.0f} pts")


def render_calculators(units: UnitSystem) -> None:
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        _panel_hydrometer(units)
    with c2:
        _panel_sugar(units)
    with c3:
        _panel_dehydrator(units)
    st.divider()
    _panel_abv()


# --- Tab 2: Active batch tracker ---------------------------------------------
def _batch_table(now: datetime, units: UnitSystem) -> pd.DataFrame:
    labels = cl.unit_labels(units)
    rows = []
    for b in _batches():
        prog = cl.batch_progress(b, now)
        metrics = cl.current_metrics(b)
        recent = sorted(b.bubble_log, key=lambda r: r.timestamp)[-12:]
        rows.append(
            {
                "ID": b.batch_id,
                "Batch": b.name,
                "Stage": f"{STAGE_EMOJI[b.stage]} {b.stage.value}",
                "Timeline": prog.fraction * 100.0,
                "Day": f"{prog.days_elapsed:.1f} / {prog.days_total}",
                "Airlock (bpm)": b.latest_bubble_rate,
                "Airlock trend": [r.bubbles_per_minute for r in recent],
                f"Temp ({labels['temp']})": (
                    None if b.current_temp_f is None
                    else cl.temp_to_display(b.current_temp_f, units)
                ),
                "SG": b.current_gravity,
                "ABV %": metrics["abv"],
                "Alerts": len(cl.evaluate_alerts(b, now)),
            }
        )
    return pd.DataFrame(rows)


def _cb_stage(batch_id: str) -> None:
    batch = _find_batch(batch_id)
    batch.stage = Stage(st.session_state[f"stage_{batch_id}"])
    _save(batch)


def _cb_log_airlock(batch_id: str, units: UnitSystem) -> None:
    batch = _find_batch(batch_id)
    now = datetime.now()
    try:
        reading = BubbleReading(
            timestamp=now,
            bubbles_per_minute=st.session_state[f"bpm_{batch_id}"],
        )
        batch.current_temp_f = cl.temp_from_display(
            st.session_state[f"ftemp_{batch_id}_{units.value}"], units
        )
        batch.bubble_log.append(reading)
    except ValidationError as exc:
        _flash("error", _format_validation_error(exc))
        return
    _save(batch)
    _flash("success", "Airlock reading logged.")


def _cb_log_gravity(batch_id: str, units: UnitSystem) -> None:
    batch = _find_batch(batch_id)
    sg = st.session_state[f"g_sg_{batch_id}"]
    temp_f = cl.temp_from_display(
        st.session_state[f"g_temp_{batch_id}_{units.value}"], units
    )
    try:
        corrected = cl.correct_hydrometer_reading(sg, temp_f)
        batch.gravity_log.append(
            GravityReading(
                timestamp=datetime.now(),
                sg_measured=sg,
                temp_f=temp_f,
                sg_corrected=round(corrected, 4),
            )
        )
        batch.current_gravity = round(corrected, 4)
    except cl.FermentValueError as exc:
        _flash("error", str(exc))
        return
    except ValidationError as exc:
        _flash("error", _format_validation_error(exc))
        return
    _save(batch)
    _flash("success", f"Gravity recorded (corrected {corrected:.4f}).")


def _cb_add_log(batch_id: str) -> None:
    batch = _find_batch(batch_id)
    try:
        batch.log.append(
            LogEntry(
                timestamp=datetime.now(),
                kind=LogKind(st.session_state[f"lk_{batch_id}"]),
                message=st.session_state[f"lm_{batch_id}"],
            )
        )
    except ValidationError as exc:
        _flash("error", _format_validation_error(exc))
        return
    _save(batch)
    _flash("success", "Log entry added.")


def _cb_delete_batch(batch_id: str) -> None:
    ss = st.session_state
    batches = _batches()
    batches.remove(_find_batch(batch_id))
    _store().delete_batch(batch_id)
    # Drop this batch's widget state so a reused ID starts clean.
    for key in list(ss):
        if key.endswith(f"_{batch_id}") or f"_{batch_id}_" in key:
            del ss[key]
    ss.pop("selected_batch_id", None)
    _flash("success", f"Deleted {batch_id}.")


def _next_batch_id() -> str:
    numbers = [
        int(b.batch_id.split("-")[-1])
        for b in _batches()
        if b.batch_id.split("-")[-1].isdigit()
    ]
    return f"FB-{max(numbers, default=0) + 1:03d}"


def _cb_add_batch(units: UnitSystem) -> None:
    ss = st.session_state
    try:
        batch = Batch(
            batch_id=_next_batch_id(),
            name=ss["nb_name"].strip(),
            product=ss["nb_product"].strip() or "Ferment",
            volume_l=cl.volume_from_display(ss[f"nb_vol_{units.value}"],
                                            units),
            start_date=datetime.combine(ss["nb_start"], time(0, 0)),
            stage=Stage(ss["nb_stage"]),
            expected_duration_days=int(ss["nb_days"]),
            original_gravity=ss["nb_og"],
            target_final_gravity=ss["nb_fg"],
            current_gravity=ss["nb_og"],
        )
    except ValidationError as exc:
        _flash("error", _format_validation_error(exc))
        return
    _batches().append(batch)
    _save(batch)
    ss["selected_batch_id"] = batch.batch_id
    _flash("success", f"Created {batch.batch_id} · {batch.name}.")


def _render_new_batch_form(units: UnitSystem) -> None:
    labels = cl.unit_labels(units)
    with st.expander("➕ New batch"):
        with st.form("new_batch"):
            c1, c2, c3 = st.columns(3)
            c1.text_input("Name", key="nb_name")
            c2.text_input("Product", value="Wine", key="nb_product")
            c3.selectbox("Stage", [s.value for s in Stage], key="nb_stage")
            c4, c5, c6 = st.columns(3)
            c4.number_input(
                f"Volume ({labels['volume']})", 0.1, 10000.0,
                3.0 if units is UnitSystem.METRIC else 0.8, 0.25,
                key=f"nb_vol_{units.value}",
            )
            c5.date_input("Start date", value=date.today(), key="nb_start")
            c6.number_input("Expected duration (days)", 1, 3650, 21,
                            key="nb_days")
            c7, c8 = st.columns(2)
            c7.number_input("Original gravity", 0.98, 1.2, 1.060, 0.001,
                            format="%.3f", key="nb_og")
            c8.number_input("Target final gravity", 0.98, 1.2, 1.010,
                            0.001, format="%.3f", key="nb_fg")
            st.form_submit_button(
                "Create batch", on_click=_cb_add_batch, args=(units,)
            )


def _render_batch_detail(batch: Batch, now: datetime,
                         units: UnitSystem) -> None:
    labels = cl.unit_labels(units)
    prog = cl.batch_progress(batch, now)
    metrics = cl.current_metrics(batch)
    color = STAGE_BADGE_COLOR[batch.stage]

    st.markdown(
        f"### {batch.batch_id} · {batch.name} "
        f":{color}-badge[{batch.stage.value}]"
    )
    st.caption(
        f"{batch.product} · "
        f"{cl.volume_to_display(batch.volume_l, units):.1f} "
        f"{labels['volume']} · started {batch.start_date:%Y-%m-%d}"
    )
    st.progress(
        prog.fraction,
        text=f"Day {prog.days_elapsed:.1f} of {prog.days_total}"
        + (" · OVERDUE" if prog.overdue else f" · {prog.fraction:.0%}"),
    )
    for alert in cl.evaluate_alerts(batch, now):
        st.warning(alert, icon="⚠️")

    m1, m2, m3, m4 = st.columns(4)
    with m1.container(border=True):
        st.metric("Current SG", f"{batch.current_gravity:.3f}"
                  if batch.current_gravity else "n/a",
                  delta=f"target {batch.target_final_gravity:.3f}"
                  if batch.target_final_gravity else None,
                  delta_color="off")
    with m2.container(border=True):
        abv = metrics["abv"]
        st.metric("Potential ABV", "n/a" if abv is None else f"{abv:.2f}%")
    with m3.container(border=True):
        att = metrics["attenuation"]
        st.metric("Attenuation", "n/a" if att is None else f"{att:.1f}%")
    with m4.container(border=True):
        rate = batch.latest_bubble_rate
        st.metric("Airlock", "n/a" if rate is None else f"{rate:.0f} bpm")

    left, right = st.columns(2, gap="large")
    bid = batch.batch_id
    with left:
        st.markdown("**Airlock bubble-rate tracker**")
        c1, c2 = st.columns(2)
        c1.number_input(
            "Bubbles / min", 0.0, 300.0, batch.latest_bubble_rate or 0.0,
            1.0, key=f"bpm_{bid}",
        )
        c2.number_input(
            f"Ferment temp ({labels['temp']})",
            value=round(
                cl.temp_to_display(batch.current_temp_f or 68.0, units), 1
            ),
            step=0.5, key=f"ftemp_{bid}_{units.value}", **_temp_bounds(units),
        )
        st.button("Log reading", key=f"logbtn_{bid}",
                  on_click=_cb_log_airlock, args=(bid, units))
        if batch.bubble_log:
            series = pd.Series(
                {r.timestamp: r.bubbles_per_minute
                 for r in sorted(batch.bubble_log,
                                 key=lambda r: r.timestamp)},
                name="bubbles/min",
            )
            st.line_chart(series, height=180)
        else:
            st.caption("No airlock readings yet.")
    with right:
        st.markdown("**Stage**")
        st.selectbox(
            "Stage", [s.value for s in Stage], key=f"stage_{bid}",
            index=list(Stage).index(batch.stage),
            on_change=_cb_stage, args=(bid,), label_visibility="collapsed",
        )
        st.markdown("**Record hydrometer reading**")
        with st.form(f"gravity_form_{bid}"):
            g1, g2 = st.columns(2)
            g1.number_input("Measured SG", 0.98, 1.2,
                            float(batch.current_gravity or 1.000), 0.001,
                            format="%.3f", key=f"g_sg_{bid}")
            g2.number_input(
                f"Sample temp ({labels['temp']})",
                value=round(cl.temp_to_display(68.0, units), 1), step=0.5,
                key=f"g_temp_{bid}_{units.value}", **_temp_bounds(units),
            )
            st.form_submit_button(
                "Correct & record (60°F cal.)",
                on_click=_cb_log_gravity, args=(bid, units),
            )
        with st.expander("Activity log"):
            with st.form(f"log_form_{bid}", clear_on_submit=True):
                k1, k2 = st.columns([1, 3])
                k1.selectbox("Type", [k.value for k in LogKind],
                             key=f"lk_{bid}")
                k2.text_input("Entry", key=f"lm_{bid}")
                st.form_submit_button("Add entry", on_click=_cb_add_log,
                                      args=(bid,))
            for entry in sorted(batch.log, key=lambda e: e.timestamp,
                                reverse=True):
                st.markdown(
                    f"- `{entry.timestamp:%m-%d %H:%M}` "
                    f"**{entry.kind.value}**: {entry.message}"
                )
        with st.expander("Manage batch"):
            st.button(
                f"Delete {bid} (cannot be undone)", key=f"del_{bid}",
                on_click=_cb_delete_batch, args=(bid,),
            )


def render_tracker(now: datetime, units: UnitSystem) -> None:
    _show_flash()
    if not _batches():
        st.info("No active ferments. Create one below.")
    else:
        st.dataframe(
            _batch_table(now, units),
            hide_index=True,
            width="stretch",
            column_config={
                "Timeline": st.column_config.ProgressColumn(
                    "Timeline", min_value=0, max_value=100, format="%d%%"
                ),
                "Airlock (bpm)": st.column_config.NumberColumn(
                    format="%.0f"
                ),
                "Airlock trend": st.column_config.LineChartColumn(
                    "Airlock trend", y_min=0
                ),
                "SG": st.column_config.NumberColumn(format="%.3f"),
                "ABV %": st.column_config.NumberColumn(format="%.1f"),
                "Alerts": st.column_config.NumberColumn(format="%d ⚠️"),
            },
        )
        selected = st.session_state.get("selected_batch_id")
        if selected:
            st.divider()
            _render_batch_detail(_find_batch(selected), now, units)
    st.divider()
    _render_new_batch_form(units)


# --- Tab 3: Production log exporter ------------------------------------------
def render_exporter(units: UnitSystem) -> None:
    st.subheader("Production sheet")
    st.caption(
        "Compile selected batches into a Markdown sheet to copy or download."
    )
    ids = [b.batch_id for b in _batches()]
    chosen = st.multiselect("Batches", ids, default=ids, key="ex_ids")
    o1, o2, o3 = st.columns(3)
    inc_alerts = o1.checkbox("Include alerts", True, key="ex_alerts")
    inc_grav = o2.checkbox("Include gravity log", True, key="ex_grav")
    inc_log = o3.checkbox("Include activity log", True, key="ex_log")

    if st.button("Compile production sheet", type="primary"):
        try:
            options = ExportOptions(
                batch_ids=chosen,
                include_alerts=inc_alerts,
                include_gravity_log=inc_grav,
                include_activity_log=inc_log,
            )
            generated = datetime.now()
            st.session_state["sheet_md"] = cl.render_production_sheet(
                [_find_batch(i) for i in options.batch_ids],
                units,
                generated,
                include_gravity_log=options.include_gravity_log,
                include_activity_log=options.include_activity_log,
                include_alerts=options.include_alerts,
            )
            st.session_state["sheet_name"] = (
                f"fermentops_sheet_{generated:%Y%m%d_%H%M}.md"
            )
        except ValidationError:
            st.error("Select at least one batch to export.")
        except cl.FermentValueError as exc:
            st.error(str(exc))

    markdown = st.session_state.get("sheet_md")
    if markdown:
        st.download_button(
            "⬇️ Download .md",
            data=markdown,
            file_name=st.session_state["sheet_name"],
            mime="text/markdown",
        )
        st.caption("Copy with the icon at the top-right of the block below.")
        st.code(markdown, language="markdown")
        with st.expander("Rendered preview"):
            st.markdown(markdown)


# --- Entrypoint --------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="FermentOps", page_icon="🍾",
                       layout="wide")
    st.markdown(METRIC_CSS, unsafe_allow_html=True)
    _init_state()
    now = datetime.now()
    units = render_sidebar(now)

    st.title("FermentOps")
    st.caption("Precision tools and tracking for micro-batch fermentation.")
    tab_calc, tab_track, tab_export = st.tabs(
        ["Precision Calculators", "Active Batch Tracker",
         "Production Log Exporter"]
    )
    with tab_calc:
        render_calculators(units)
    with tab_track:
        render_tracker(now, units)
    with tab_export:
        render_exporter(units)


main()
