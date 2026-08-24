# F1 Team Points Predictor

🇺🇸 English | [🇧🇷 Português](READMEpt.md)

End-to-end data pipeline (collection → data engineering → predictive model) to
forecast a **Formula 1 team's points per race**, using data exclusively from the
current technical regulation era (2026).

Portfolio project built during semester break, focused on solid data engineering
practices: resilient collection with rate limiting, layered storage (raw →
processed), a containerized relational database, and a reproducible pipeline.

## Why 2026 only?

The 2026 F1 season introduced a completely new technical regulation (hybrid
power unit, active aerodynamics, new teams). Mixing data across different
regulation eras would distort the model, since relative team performance isn't
comparable between regulations. For that reason, the target variable (team
points) is trained **exclusively** on 2026 data. Features based on fixed
characteristics — such as a driver's history at a given circuit — still use
historical data (2019-2025), since those depend on driver skill rather than
the car.

## Project status

- [x] **Phase 1 — Data Collection**: calendar, race results, qualifying, pit
      stops, race status, current grid, and driver-per-circuit history
- [x] **Phase 2 — Data Engineering**: relational schema, PostgreSQL database
      containerized with Docker, and ETL pipeline (raw → database) — **run and
      verified against a real Postgres instance** (not just dry-run)
- [~] **Phase 3 — Predictive model**: feature pipeline and a leakage-free
      expanding-window backtest are in place; first models beat the naive
      baselines, though not yet by a statistically conclusive margin (see
      [Modeling results](#modeling-results))
- [ ] Phase 4 — Dashboard or API serving predictions

Data currently covers the 2026 season through **round 12**, collected on
2026-08-24.

## Tech stack

| Layer | Technology |
|---|---|
| Data collection | Python, `requests` |
| Raw storage | JSON (raw layer) |
| Database | PostgreSQL 16 (via Docker) |
| ETL | Python, `pandas`, `sqlalchemy` |
| Modeling | `scikit-learn` (planned) |
| Environment | WSL2 (Ubuntu) + Docker Desktop |

## Data sources

- **[Jolpica-F1](https://api.jolpi.ca)** — public API, successor to the Ergast
  API, providing race results, qualifying, pit stops, race status, and both
  historical and current-season standings.
- **Track type classification** — manually curated
  (`data/lookup/track_types.csv`), since no structured public source exists
  for this categorization. Validated against real `circuit_id`s returned by
  the API — all match except `madring`, a new-for-2026 circuit that hasn't
  hosted a race yet.

## Project structure

```
f1-team-points-predictor/
├── data/
│   ├── raw/              # raw data, exactly as returned by the API
│   ├── processed/        # cleaned data, ready for database loading
│   └── lookup/           # manually curated reference tables
├── src/
│   ├── collectors/       # data collection scripts (Phase 1)
│   ├── etl/               # schema.sql and transform/load pipeline (Phase 2)
│   └── models/             # model training and evaluation (Phase 3)
├── docker-compose.yml        # spins up the containerized PostgreSQL instance
└── requirements.txt
```

## Getting started

**Prerequisites:** WSL2 (Ubuntu) with Python 3.10+, Docker Desktop with WSL2
integration enabled.

```bash
# Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Database
docker compose up -d

# Data collection (Phase 1)
python -m src.collectors.collect_season --season 2026
python -m src.collectors.collect_current_grid --season 2026
python -m src.collectors.collect_driver_circuit_history --seasons 2019 2020 2021 2022 2023 2024 2025

# ETL (Phase 2)
python -m src.etl.load_to_postgres
```

Raw data is saved under `data/raw/`. The database schema is created
automatically the first time the PostgreSQL container starts (via
`docker-entrypoint-initdb.d`).

## Database design

The database has two central views that avoid duplicating raw data:

- `team_race_points` — sums both drivers' points per team/race (this is the
  predictive model's **target**)
- `driver_circuit_history` — results from previous seasons by driver and
  circuit (this is the **feature** for driver track history)

See `src/etl/schema.sql` for the full schema.

## Known issue: duplicate race blocks in paginated raw data

The Jolpica-F1 `/results/` endpoint paginates by **individual result row**,
not by race. Since each race has ~20-22 results and pages are fetched in
batches of 100, a race can straddle a page boundary and show up as two
separate, partial blocks in the raw JSON (e.g. round 5 as 12+10 results,
round 10 as 2+20). This doesn't corrupt the database — `load_to_postgres.py`
upserts by `(race_id, driver_id)`, so both partial blocks together still
produce the correct, complete set of results — but it does mean the raw JSON
should not be assumed to have one block per race. Worth fixing in the
collector (e.g. re-assembling split blocks, or paginating by race instead)
before relying on `data/raw/races/*.json` for anything outside this ETL.

## Modeling results

```bash
python -m src.models.build_features   # DB -> data/processed/team_race_features.csv
python -m src.models.train            # expanding-window backtest
```

**Features** are strictly pre-race. Team lineup and grid come from the
`qualifying` table (Saturday) rather than `results`, so the results table is
used only to build the target — a race outcome cannot leak into a feature by
accident. Form features (`form_last3`, `form_todate`, `dnf_rate_todate`) are
shifted one round, so the race being predicted never enters its own feature.
Verified programmatically: 0 rows where the current race leaks into its form
features.

**Validation** is an expanding-window backtest: for each test round, the model
trains only on earlier rounds. Random k-fold would train on future races to
predict past ones, inflating the score in a way that never survives real use.

Backtest over rounds 6-12 (77 predictions per model):

| Model | MAE | RMSE | Within-race Spearman |
|---|---|---|---|
| Random Forest | **3.75** | 5.57 | **0.871** |
| Ridge | 4.06 | **5.56** | 0.864 |
| Baseline: team's season-to-date mean | 4.42 | 6.38 | 0.819 |
| Baseline: team's last race | 4.96 | 7.80 | 0.835 |
| Baseline: global mean | 9.73 | 11.22 | — |

**Honest reading of these numbers.** The Random Forest beats the strongest
naive baseline by 0.67 MAE and wins in 6 of the 7 test rounds, but a paired
bootstrap puts the 95% CI of that gain at **[-0.12, +1.46] — it crosses
zero**. So the edge is suggestive (P(better) ≈ 0.95), not conclusive. That is
the expected outcome with 121 rows: F1 gives ~11 teams × ~23 races per season,
and restricting to the 2026 regulation caps the data hard. The gap should
become decidable as the season adds rounds.

The Ridge coefficients are physically sensible, which is a good sign the
pipeline isn't fitting noise: season-to-date form dominates (+3.90), better
(lower) grid positions raise predicted points (-2.09 on `grid_best`), and
track type contributes almost nothing (|coef| < 0.04) — with 5 categories over
121 rows there isn't enough data to learn track effects.

## Next steps

- Re-run the backtest as rounds are added — the RF-vs-baseline gap is the
  number to watch
- Try a two-stage target (points scored | scored at all) given how many rows
  are exactly 0
- Consider fixing the pagination issue above in the collector

## Author

Built as part of a data engineering / data science portfolio by a Computer
Engineering student.
