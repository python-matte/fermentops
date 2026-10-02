"""Unit tests for the pure calculation logic in ``core_logic``."""

from datetime import datetime, timedelta

import pytest

import core_logic as cl
from schemas import Batch, BubbleReading, LogEntry, Stage, UnitSystem

NOW = datetime(2026, 1, 15, 12, 0)


def make_batch(**overrides) -> Batch:
    """A healthy Primary batch, 3 days in, with a fresh airlock reading."""
    fields = dict(
        batch_id="FB-001",
        name="Test Wine",
        product="Wine",
        volume_l=3.0,
        start_date=NOW - timedelta(days=3),
        stage=Stage.PRIMARY,
        expected_duration_days=21,
        original_gravity=1.090,
        target_final_gravity=0.996,
        current_gravity=1.060,
        current_temp_f=68.0,
        bubble_log=[
            BubbleReading(
                timestamp=NOW - timedelta(hours=2), bubbles_per_minute=30
            )
        ],
    )
    fields.update(overrides)
    return Batch(**fields)


# --- Unit conversion -------------------------------------------------------
class TestUnitConversion:
    def test_known_temperature_points(self):
        assert cl.f_to_c(32.0) == pytest.approx(0.0)
        assert cl.f_to_c(212.0) == pytest.approx(100.0)
        assert cl.c_to_f(37.0) == pytest.approx(98.6)

    @pytest.mark.parametrize("value", [-40.0, 0.0, 20.5, 100.0])
    def test_temperature_round_trip(self, value):
        assert cl.f_to_c(cl.c_to_f(value)) == pytest.approx(value)

    def test_known_volume_and_weight_points(self):
        assert cl.gallons_to_litres(1.0) == pytest.approx(3.785411784)
        assert cl.kg_to_lb(1.0) == pytest.approx(2.2046226, rel=1e-6)
        assert cl.grams_to_oz(28.349523125) == pytest.approx(1.0)

    @pytest.mark.parametrize("units", list(UnitSystem))
    def test_display_round_trips(self, units):
        assert cl.temp_from_display(
            cl.temp_to_display(70.0, units), units
        ) == pytest.approx(70.0)
        assert cl.volume_from_display(
            cl.volume_to_display(5.0, units), units
        ) == pytest.approx(5.0)
        assert cl.weight_from_display(
            cl.weight_to_display(2.0, units), units
        ) == pytest.approx(2.0)

    def test_canonical_units_pass_through(self):
        assert cl.temp_to_display(70.0, UnitSystem.IMPERIAL) == 70.0
        assert cl.volume_to_display(5.0, UnitSystem.METRIC) == 5.0
        assert cl.weight_to_display(2.0, UnitSystem.METRIC) == 2.0

    def test_unit_labels(self):
        assert cl.unit_labels(UnitSystem.METRIC)["temp"] == "°C"
        assert cl.unit_labels(UnitSystem.IMPERIAL)["volume"] == "gal"


# --- Hydrometer correction -------------------------------------------------
class TestHydrometerCorrection:
    def test_no_correction_at_calibration_temperature(self):
        assert cl.correct_hydrometer_reading(1.050, 60.0) == pytest.approx(
            1.050
        )
        assert cl.correct_hydrometer_reading(
            1.050, 68.0, 68.0
        ) == pytest.approx(1.050)

    def test_warm_sample_reads_low_so_correction_adds(self):
        corrected = cl.correct_hydrometer_reading(1.050, 77.0)
        assert corrected > 1.050
        # Widely published brewing tables give ~1.052 for 1.050 at 77 F.
        assert corrected == pytest.approx(1.052, abs=5e-4)

    def test_cold_sample_reads_high_so_correction_subtracts(self):
        assert cl.correct_hydrometer_reading(1.050, 40.0) < 1.050

    def test_matches_published_polynomial(self):
        def p(t):
            return (
                1.00130346
                - 0.000134722124 * t
                + 0.00000204052596 * t**2
                - 0.00000000232820948 * t**3
            )

        expected = 1.090 * p(100.0) / p(68.0)
        assert cl.correct_hydrometer_reading(
            1.090, 100.0, 68.0
        ) == pytest.approx(expected, rel=1e-12)

    @pytest.mark.parametrize("sg", [0.9, 1.3, float("nan"), float("inf")])
    def test_rejects_bad_gravity(self, sg):
        with pytest.raises(cl.FermentValueError):
            cl.correct_hydrometer_reading(sg, 60.0)

    @pytest.mark.parametrize("temp", [31.9, 212.1, float("nan")])
    def test_rejects_bad_temperature(self, temp):
        with pytest.raises(cl.FermentValueError):
            cl.correct_hydrometer_reading(1.050, temp)
        with pytest.raises(cl.FermentValueError):
            cl.correct_hydrometer_reading(1.050, 60.0, temp)

    def test_rejects_non_numeric_input(self):
        with pytest.raises(cl.FermentValueError):
            cl.correct_hydrometer_reading("1.050", 60.0)  # type: ignore


# --- ABV and attenuation ---------------------------------------------------
class TestAbvAndAttenuation:
    def test_potential_abv(self):
        assert cl.potential_abv(1.090, 1.010) == pytest.approx(10.5)
        assert cl.potential_abv(1.050, 1.050) == 0.0

    def test_attenuation(self):
        assert cl.attenuation_rate(1.090, 1.010) == pytest.approx(
            88.888, abs=1e-2
        )
        assert cl.attenuation_rate(1.050, 1.050) == 0.0
        assert cl.attenuation_rate(1.050, 1.000) == pytest.approx(100.0)

    def test_final_above_start_is_rejected(self):
        with pytest.raises(cl.FermentValueError, match="cannot exceed"):
            cl.potential_abv(1.010, 1.090)
        with pytest.raises(cl.FermentValueError, match="cannot exceed"):
            cl.attenuation_rate(1.010, 1.090)

    def test_attenuation_rejects_start_of_exactly_one(self):
        with pytest.raises(cl.FermentValueError, match="above 1.000"):
            cl.attenuation_rate(1.000, 1.000)

    def test_attenuation_rejects_start_below_one(self):
        with pytest.raises(cl.FermentValueError):
            cl.attenuation_rate(0.990, 0.985)

    @pytest.mark.parametrize("bad", [0.979, 1.201])
    def test_out_of_range_gravity(self, bad):
        with pytest.raises(cl.FermentValueError):
            cl.potential_abv(bad, 1.000)
        with pytest.raises(cl.FermentValueError):
            cl.potential_abv(1.050, bad)


# --- Sugar addition --------------------------------------------------------
class TestSugarAddition:
    def test_sucrose_worked_example(self):
        # 1.050 -> 1.090 is 10 Brix; 10 * 10.4 g/L * 3 L = 312 g.
        result = cl.sugar_addition(3.0, 1.050, 1.090)
        assert result.brix_increase == pytest.approx(10.0)
        assert result.grams_per_litre == pytest.approx(104.0)
        assert result.sugar_g == pytest.approx(312.0)
        assert result.gravity_points_added == pytest.approx(40.0)
        assert result.abv_gain == pytest.approx(0.04 * 131.25)
        assert result.sugar_type == "Sucrose"

    def test_dextrose_needs_more_mass(self):
        sucrose = cl.sugar_addition(3.0, 1.050, 1.090, "Sucrose")
        dextrose = cl.sugar_addition(3.0, 1.050, 1.090, "Dextrose")
        assert dextrose.sugar_g == pytest.approx(sucrose.sugar_g * 46 / 42)

    def test_scales_linearly_with_volume(self):
        small = cl.sugar_addition(1.0, 1.050, 1.090)
        large = cl.sugar_addition(10.0, 1.050, 1.090)
        assert large.sugar_g == pytest.approx(small.sugar_g * 10)

    @pytest.mark.parametrize("target", [1.050, 1.040])
    def test_target_must_exceed_start(self, target):
        with pytest.raises(cl.FermentValueError, match="above starting"):
            cl.sugar_addition(3.0, 1.050, target)

    @pytest.mark.parametrize("volume", [0.0, -1.0, float("nan")])
    def test_volume_must_be_positive(self, volume):
        with pytest.raises(cl.FermentValueError):
            cl.sugar_addition(volume, 1.050, 1.090)

    def test_unknown_sugar_type(self):
        with pytest.raises(cl.FermentValueError, match="Unknown sugar"):
            cl.sugar_addition(3.0, 1.050, 1.090, "Honey")


# --- Dehydrator yield ------------------------------------------------------
class TestDehydratorYield:
    def test_worked_example(self):
        result = cl.dehydrator_yield(5.0, 75.0, 6, 85.0)
        assert result.dry_kg == pytest.approx(1.25)
        assert result.water_removed_kg == pytest.approx(3.75)
        assert result.yield_pct == pytest.approx(25.0)
        # (85 - 75) / (100 - 75) * 100 = 40 %
        assert result.final_moisture_pct == pytest.approx(40.0)
        assert result.wet_per_tray_kg == pytest.approx(5.0 / 6)
        assert result.dry_per_tray_kg == pytest.approx(1.25 / 6)
        assert result.trays == 6

    def test_mass_balance(self):
        result = cl.dehydrator_yield(7.3, 60.0, 4)
        assert result.dry_kg + result.water_removed_kg == pytest.approx(
            result.wet_kg
        )

    def test_removing_all_available_water_leaves_bone_dry(self):
        result = cl.dehydrator_yield(1.0, 85.0, 1, 85.0)
        assert result.final_moisture_pct == pytest.approx(0.0)

    def test_reduction_cannot_exceed_initial_moisture(self):
        with pytest.raises(cl.FermentValueError, match="cannot exceed"):
            cl.dehydrator_yield(5.0, 90.0, 6, 85.0)

    @pytest.mark.parametrize("weight", [0.0, -2.0])
    def test_weight_must_be_positive(self, weight):
        with pytest.raises(cl.FermentValueError):
            cl.dehydrator_yield(weight, 50.0, 3)

    @pytest.mark.parametrize("trays", [0, -1, 2.5, True])
    def test_trays_must_be_a_whole_number_at_least_one(self, trays):
        with pytest.raises(cl.FermentValueError, match="trays"):
            cl.dehydrator_yield(5.0, 50.0, trays)  # type: ignore

    @pytest.mark.parametrize("reduction", [0.0, 100.0, -5.0])
    def test_reduction_range(self, reduction):
        with pytest.raises(cl.FermentValueError):
            cl.dehydrator_yield(5.0, reduction, 3)

    @pytest.mark.parametrize("initial", [-1.0, 100.0])
    def test_initial_moisture_range(self, initial):
        with pytest.raises(cl.FermentValueError):
            cl.dehydrator_yield(5.0, 50.0, 3, initial)


# --- Batch progress --------------------------------------------------------
class TestBatchProgress:
    def test_midway(self):
        progress = cl.batch_progress(make_batch(), NOW)
        assert progress.days_elapsed == pytest.approx(3.0)
        assert progress.fraction == pytest.approx(3 / 21)
        assert not progress.overdue

    def test_overdue_clamps_fraction(self):
        batch = make_batch(start_date=NOW - timedelta(days=30))
        progress = cl.batch_progress(batch, NOW)
        assert progress.fraction == 1.0
        assert progress.overdue

    def test_future_start_never_negative(self):
        batch = make_batch(start_date=NOW + timedelta(days=2))
        progress = cl.batch_progress(batch, NOW)
        assert progress.days_elapsed == 0.0
        assert progress.fraction == 0.0


# --- Alerts ----------------------------------------------------------------
class TestAlerts:
    def test_healthy_batch_has_no_alerts(self):
        assert cl.evaluate_alerts(make_batch(), NOW) == []

    @pytest.mark.parametrize(
        "stage,temp",
        [
            (Stage.PRIMARY, 80.0),
            (Stage.PRIMARY, 55.0),
            (Stage.COLD_CRASH, 60.0),
            (Stage.AGING, 72.0),
        ],
    )
    def test_temperature_outside_stage_window(self, stage, temp):
        alerts = cl.evaluate_alerts(
            make_batch(stage=stage, current_temp_f=temp), NOW
        )
        assert any("outside" in a for a in alerts)

    def test_temperature_window_boundaries_are_inclusive(self):
        for temp in (59.0, 77.0):
            assert cl.evaluate_alerts(
                make_batch(current_temp_f=temp), NOW
            ) == []

    def test_unknown_temperature_raises_no_alert(self):
        assert cl.evaluate_alerts(make_batch(current_temp_f=None), NOW) == []

    def test_stale_airlock_in_primary(self):
        stale = [
            BubbleReading(
                timestamp=NOW - timedelta(hours=30), bubbles_per_minute=20
            )
        ]
        alerts = cl.evaluate_alerts(make_batch(bubble_log=stale), NOW)
        assert "No airlock reading in the last 24 hours" in alerts

    def test_never_logged_airlock_alerts_after_a_day(self):
        batch = make_batch(bubble_log=[])
        assert "No airlock readings logged yet" in cl.evaluate_alerts(
            batch, NOW
        )
        fresh = make_batch(bubble_log=[], start_date=NOW - timedelta(hours=6))
        assert cl.evaluate_alerts(fresh, NOW) == []

    def test_airlock_alerts_only_apply_to_primary(self):
        batch = make_batch(stage=Stage.SECONDARY, bubble_log=[])
        assert cl.evaluate_alerts(batch, NOW) == []

    def test_stuck_fermentation(self):
        silent = [
            BubbleReading(
                timestamp=NOW - timedelta(hours=1), bubbles_per_minute=0
            )
        ]
        batch = make_batch(bubble_log=silent, current_gravity=1.060)
        alerts = cl.evaluate_alerts(batch, NOW)
        assert any("stuck fermentation" in a for a in alerts)

    def test_silent_airlock_at_target_gravity_is_not_stuck(self):
        silent = [
            BubbleReading(
                timestamp=NOW - timedelta(hours=1), bubbles_per_minute=0
            )
        ]
        batch = make_batch(bubble_log=silent, current_gravity=0.997)
        assert cl.evaluate_alerts(batch, NOW) == []

    def test_silent_airlock_in_first_two_days_is_not_stuck(self):
        silent = [
            BubbleReading(
                timestamp=NOW - timedelta(hours=1), bubbles_per_minute=0
            )
        ]
        batch = make_batch(
            bubble_log=silent,
            start_date=NOW - timedelta(days=1),
            current_gravity=1.080,
        )
        assert cl.evaluate_alerts(batch, NOW) == []

    def test_overdue_batch(self):
        batch = make_batch(
            stage=Stage.AGING,
            start_date=NOW - timedelta(days=40),
            current_temp_f=60.0,
        )
        alerts = cl.evaluate_alerts(batch, NOW)
        assert alerts == ["Past expected duration (21 days)"]


# --- Current metrics -------------------------------------------------------
class TestCurrentMetrics:
    def test_metrics(self):
        metrics = cl.current_metrics(make_batch(current_gravity=1.010))
        assert metrics["abv"] == pytest.approx(10.5)
        assert metrics["attenuation"] == pytest.approx(88.888, abs=1e-2)

    def test_no_gravity_reading(self):
        assert cl.current_metrics(make_batch(current_gravity=None)) == {
            "abv": None,
            "attenuation": None,
        }

    def test_gravity_above_og_degrades_to_none(self):
        metrics = cl.current_metrics(make_batch(current_gravity=1.100))
        assert metrics == {"abv": None, "attenuation": None}


# --- Production sheet ------------------------------------------------------
class TestProductionSheet:
    def test_requires_at_least_one_batch(self):
        with pytest.raises(cl.FermentValueError):
            cl.render_production_sheet([], UnitSystem.METRIC, NOW)

    def test_contains_summary_and_details(self):
        batch = make_batch(
            log=[
                LogEntry(
                    timestamp=NOW - timedelta(days=1), message="Pitched yeast"
                )
            ],
            notes="Punch down twice daily.",
        )
        sheet = cl.render_production_sheet([batch], UnitSystem.METRIC, NOW)
        assert sheet.startswith("# FermentOps Production Sheet")
        assert "| FB-001 | Test Wine | Primary |" in sheet
        assert "## FB-001 - Test Wine" in sheet
        assert "Pitched yeast" in sheet
        assert "> Punch down twice daily." in sheet
        assert sheet.endswith("\n")

    def test_options_switch_sections_off(self):
        batch = make_batch(
            log=[LogEntry(timestamp=NOW, message="Racked")],
            current_temp_f=90.0,
        )
        sheet = cl.render_production_sheet(
            [batch],
            UnitSystem.METRIC,
            NOW,
            include_gravity_log=False,
            include_activity_log=False,
            include_alerts=False,
        )
        assert "Racked" not in sheet
        assert "**Alerts**" not in sheet

    def test_alerts_are_listed_when_enabled(self):
        sheet = cl.render_production_sheet(
            [make_batch(current_temp_f=90.0)], UnitSystem.METRIC, NOW
        )
        assert "WARNING: Temperature 90.0°F is outside" in sheet

    def test_units_are_applied(self):
        batch = make_batch(volume_l=3.785411784, current_temp_f=68.0)
        metric = cl.render_production_sheet([batch], UnitSystem.METRIC, NOW)
        imperial = cl.render_production_sheet(
            [batch], UnitSystem.IMPERIAL, NOW
        )
        assert "Volume (L)" in metric and "20.0 °C" in metric
        assert "Volume (gal)" in imperial and "68.0 °F" in imperial
        assert "**Volume:** 1.00 gal" in imperial
