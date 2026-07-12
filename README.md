# f1-points-predictor-model

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
- [x] **Phase 2 — Data Engineering**: relational schema designed, PostgreSQL
      database containerized with Docker
- [ ] Phase 2.1 — ETL pipeline (raw → database)
- [ ] Phase 3 — Predictive model (team points per race regression)
- [ ] Phase 4 — Dashboard or API serving predictions

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
  for this categorization.

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
├── notebooks/               # exploration and prototyping
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

## Author

Built as part of a data engineering / data science portfolio by a Computer
Engineering student.
