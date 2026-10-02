# Formulas, validation and alert rules

Every formula here lives in [`core_logic.py`](../core_logic.py) and is covered by [`tests/test_core_logic.py`](../tests/test_core_logic.py). The worked examples below are the same numbers the tests assert.

**Canonical internal units:** litres, kilograms, grams, °F and specific gravity (SG). The Metric/Imperial toggle only changes what is displayed and typed; values are converted at the edge of the UI and nowhere else.

These are standard homebrewing approximations. Read [Limitations](#limitations) before relying on them for anything other than a hobby.

---

## 1. Hydrometer temperature correction

A hydrometer is only exact at the temperature it was calibrated for (usually 60 °F / 15.6 °C or 68 °F / 20 °C, printed on the stem). A warm sample is less dense, so the hydrometer floats lower and reads **low**; the correction adds the difference back.

```
SG_corr = SG_meas × P(T_meas) / P(T_cal)

P(T) = 1.00130346 − 0.000134722124·T + 0.00000204052596·T² − 0.00000000232820948·T³
```

`T` is in °F. `P` is a cubic fit to the density of water against temperature, and the *ratio* of the two evaluations is what matters. The default calibration temperature is 60 °F.

**Worked example:** a reading of 1.050 at 77 °F, hydrometer calibrated at 60 °F, corrects to **1.0520**.

## 2. Potential ABV

```
ABV % = (SG_start − SG_final) × 131.25
```

**Worked example:** OG 1.090, FG 1.010 → `0.080 × 131.25 =` **10.5 %**.

## 3. Apparent attenuation

The share of the original sugar that has been consumed:

```
attenuation % = (SG_start − SG_final) / (SG_start − 1.000) × 100
```

**Worked example:** OG 1.090, FG 1.010 → `0.080 / 0.090 × 100 =` **88.9 %**.

A starting SG of exactly 1.000 would divide by zero and is rejected with a clear message.

## 4. Sugar boost

How much sugar raises a given volume from one gravity to another:

```
brix_increase = (SG_target − SG_start) / 0.004
sugar_g       = brix_increase × 10.4 × volume_L × type_factor
```

This uses the rules of thumb **1 °Brix ≈ 0.004 SG** and **1 °Brix ≈ 10.4 g of sugar per litre**.

| Sugar | `type_factor` | Why |
|---|---|---|
| Sucrose (white table sugar) | 1.0 | Reference |
| Dextrose (corn sugar) | 46 / 42 ≈ 1.095 | Contributes fewer gravity points per gram (≈42 vs ≈46) |

The UI exposes sucrose only. Dextrose is implemented and tested in `core_logic.py` but is not offered in the interface.

**Worked example:** 3 L from 1.050 to 1.090 is 10 °Brix, so `10 × 10.4 × 3 =` **312 g**, which adds about 5.25 % ABV (`0.040 × 131.25`).

**Not modelled:** the sugar's own volume (displacement). Dissolving a lot of sugar raises the total volume slightly, so the real gravity lands a touch below target for large boosts.

## 5. Dehydrator yield

`moisture reduction` is the percentage of the **initial wet mass** that is removed as water.

```
dry_kg              = wet_kg × (1 − reduction / 100)
water_removed_kg    = wet_kg − dry_kg
final_moisture %    = (initial_moisture − reduction) / (100 − reduction) × 100
per-tray load       = wet_kg / trays      (and dry_kg / trays for the output)
```

Initial moisture defaults to 85 % and is editable. The reduction cannot exceed it, because you cannot remove more water than the material contains.

**Worked example:** 5 kg of fruit at 85 % moisture, 75 % reduction, 6 trays:
dry yield `5 × 0.25 =` **1.25 kg**, final moisture `(85 − 75) / 25 × 100 =` **40 %**, wet load **0.83 kg** per tray.

---

## Defensive validation

Calculations refuse to run on nonsense and say why, rather than returning a plausible wrong number. Every case below is tested.

| Input | Accepted range / rule |
|---|---|
| Specific gravity | 0.980 – 1.200 |
| Temperature | 32 – 212 °F |
| Any number | Must be finite (NaN and ∞ rejected) |
| Final SG | Must not exceed starting SG (ABV, attenuation) |
| Starting SG for attenuation | Must be above 1.000 |
| Sugar target SG | Must be above starting SG |
| Volume, wet weight | Greater than zero |
| Trays | Whole number, at least 1 |
| Moisture percentages | Initial in [0, 100), reduction in (0, 100), reduction ≤ initial |

In the UI a rejected input shows an inline message under the panel; the app never crashes on bad input.

## Alert rules

Evaluated for every batch against an explicit `now`, so they are deterministic and testable.

| Alert | Fires when |
|---|---|
| **Temperature outside window** | Current temperature is outside the stage's range (bounds are inclusive) |
| **Possible stuck fermentation** | Stage is Primary, the latest airlock reading is under 1 bubble/min, at least 2 days have elapsed, **and** current gravity is more than 0.004 above target |
| **No airlock reading in 24 h** | Primary only: the newest reading is over 24 hours old |
| **No airlock readings logged yet** | Primary only: nothing logged and at least 1 day has elapsed |
| **Past expected duration** | Elapsed days exceed the batch's expected duration |

Stage temperature windows:

| Stage | Window |
|---|---|
| Primary | 59 – 77 °F (15 – 25 °C) |
| Secondary | 59 – 77 °F (15 – 25 °C) |
| Cold Crash | 30 – 45 °F (−1 – 7 °C) |
| Aging | 50 – 68 °F (10 – 20 °C) |

Hydrometer readings recorded in the tracker are corrected against a 60 °F calibration temperature.

## Limitations

- **ABV is a potential/apparent figure.** `131.25 × ΔSG` is the common approximation; more elaborate formulas exist and diverge at high gravity. Alcohol also lowers the apparent gravity, which the simple formula ignores.
- **°Brix ↔ SG ↔ grams per litre** are rules of thumb that are best near typical homebrew gravities.
- **Sugar displacement is ignored** (see above).
- **Dehydrator numbers** assume uniform moisture and no loss of solids.
- **Alert thresholds are reasonable defaults, not universal truths.** Different yeasts and styles have different comfortable ranges.
