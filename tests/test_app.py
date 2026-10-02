"""End-to-end smoke tests that drive the real Streamlit UI headlessly."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TIMEOUT = 30


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("FERMENTOPS_DEMO", "1")
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    # AppTest cannot re-run a selectbox that uses ``format_func`` until its
    # value is the formatted label, so select the first batch explicitly.
    at.sidebar.selectbox[0].select_index(0)
    return at


def test_app_starts_without_exceptions(app):
    assert not app.exception


def test_demo_mode_is_announced(app):
    captions = [c.value for c in app.sidebar.caption]
    assert any("Demo mode" in c for c in captions)


def test_three_tabs_are_present(app):
    labels = [t.label for t in app.tabs]
    assert labels == [
        "Precision Calculators",
        "Active Batch Tracker",
        "Production Log Exporter",
    ]


def test_four_demo_batches_are_seeded(app):
    options = app.sidebar.selectbox[0].options
    assert len(options) == 4
    assert options[0].startswith("FB-001")


def test_default_calculator_values_render_results(app):
    metrics = {m.label: m.value for m in app.tabs[0].metric}
    assert metrics["Corrected SG"] == "1.0520"
    assert metrics["Potential ABV"] == "10.50%"
    assert metrics["Attenuation"] == "88.9%"
    assert metrics["White sugar to add"] == "312 g"


def test_invalid_calculator_input_shows_an_error_not_a_crash(app):
    app.number_input(key="abv_fg").set_value(1.200).run()
    assert not app.exception
    assert any("cannot exceed" in e.value for e in app.error)


def test_unit_toggle_switches_labels(app):
    app.sidebar.radio[0].set_value("Imperial").run()
    assert not app.exception
    labels = [n.label for n in app.number_input]
    assert any("(°F)" in label for label in labels)
    assert any("(gal)" in label for label in labels)


def test_logging_an_airlock_reading(app):
    app.number_input(key="bpm_FB-001").set_value(42.0)
    app.button(key="logbtn_FB-001").click().run()
    assert not app.exception
    assert any("Airlock reading logged" in s.value for s in app.success)


def test_creating_a_batch(app):
    app.text_input(key="nb_name").set_value("Test Mead")
    app.run()
    app.sidebar.selectbox[0].select_index(0)  # see the fixture's note
    next(
        b for b in app.button if b.label == "Create batch"
    ).click().run()
    assert not app.exception
    ids = [o for o in app.sidebar.selectbox[0].options]
    assert any(o.startswith("FB-005") and "Test Mead" in o for o in ids)


def test_creating_a_batch_without_a_name_is_rejected(app):
    next(b for b in app.button if b.label == "Create batch").click().run()
    assert not app.exception
    assert len(app.sidebar.selectbox[0].options) == 4
    assert app.error


def test_compiling_a_production_sheet(app):
    next(
        b for b in app.button if b.label == "Compile production sheet"
    ).click().run()
    assert not app.exception
    sheet = app.session_state["sheet_md"]
    assert sheet.startswith("# FermentOps Production Sheet")
    assert "FB-004" in sheet


def test_deleting_a_batch(app):
    app.button(key="del_FB-001").click().run()
    assert not app.exception
    assert len(app.sidebar.selectbox[0].options) == 3
