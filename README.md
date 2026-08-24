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
| **Two-stage (hurdle) + RF** | **3.53** | **5.40** | **0.872** |
| Random Forest | 3.75 | 5.57 | 0.871 |
| Two-stage (hurdle) + linear | 3.77 | 5.44 | 0.868 |
| Ridge | 4.06 | 5.56 | 0.864 |
| Baseline: team's season-to-date mean | 4.42 | 6.38 | 0.819 |
| Baseline: team's last race | 4.96 | 7.80 | 0.835 |
| Baseline: global mean | 9.73 | 11.22 | — |

### The two-stage (hurdle) model

39% of rows are exactly 0 points, and those zeros aren't "few points" — only
the top 10 finishers score at all, so a backmarker scoring nothing is a
different event from a strong team having a bad day. `src/models/two_stage.py`
splits the question in two: a classifier for *does this team score?* and a
regressor trained **only on scoring rows** for *how much, given it scored?*.
The prediction is `P(score) × E[points | scored]`.

Paired bootstrap (10k resamples) on the gain in MAE:

| Comparison | Gain | 95% CI | P(better) |
|---|---|---|---|
| Two-stage RF vs single-stage RF | +0.22 | [+0.03, +0.42] | 0.991 |
| Two-stage RF vs season-to-date baseline | +0.89 | [+0.01, +1.78] | 0.977 |

Both CIs now exclude zero — narrowly for the baseline comparison. The
two-stage model is a real, if small, improvement over the single-stage one.

### Testing it on Mercedes

Mercedes scored in **all 12 races**, so the classification stage is trivially
~1 for them and the two-stage design should, in principle, change nothing.
It still helped (MAE 6.33 vs 7.14 for single-stage RF; CI [+0.26, +1.38]).
The reason is the *second* stage, not the first: a single regressor trained on
all rows is dragged toward zero by the 39% of rows that are zeros, which
systematically under-predicts the strong teams. Training the conditional stage
only on scoring rows removes that pull.

**The more important finding is a negative one.** Across all teams, predicted
vs actual correlates at **+0.88**. Within Mercedes alone it is **-0.16
(p=0.72)** — no signal at all. Mercedes' actual points swing from 18 to 40
(sd 8.2) while the model predicts 23-27 every race (sd 1.3), with near-zero
bias (+0.22). So the model has essentially **no ability to predict a single
strong team's race-to-race variation**; what it does well is rank teams
against each other and track the level of a team better than a lagging
average. Anyone reading the headline MAE should know the skill is almost
entirely "which team is this", not "what will happen this Sunday".

The Ridge coefficients are physically sensible, which is a good sign the
pipeline isn't fitting noise: season-to-date form dominates (+3.90), better
(lower) grid positions raise predicted points (-2.09 on `grid_best`), and
track type contributes almost nothing (|coef| < 0.04) — with 5 categories over
121 rows there isn't enough data to learn track effects.

## Predictions

```bash
python -m src.models.predict --modo holdout   # re-predict the last completed race
python -m src.models.predict --modo proxima   # forecast the next race
```

**Holdout, round 12 (Dutch GP)** — trained on rounds 2-11 only, MAE **3.06**.
It nailed the non-scorers and Audi exactly, but under-predicted both
33-point scores (McLaren, Mercedes → ~24) and over-predicted RB (6.1 vs 0).

**Next race, round 13 (Italian GP at Monza)** carries a real caveat: its
qualifying hasn't happened yet, so the grid features don't exist and this
forecast uses a weaker form-only model. Predicted: Mercedes 23.2, Ferrari
21.9, McLaren 19.4, Red Bull 18.7, then everyone else under 4.

That forecast also exposes a genuine flaw worth knowing about: **Cadillac is
predicted 1.2 points despite never having scored all season** — ahead of
Williams and Haas, who have. Without grid data the model leans on
`hist_circuit_points`, and Cadillac fields Pérez (8.0 avg at Monza) and
Bottas (7.33), records earned at Red Bull and Mercedes/Alfa Romeo rather than
in a first-year Cadillac. Driver circuit history does not transfer across a
change of car, and the full model only avoids this because grid position
reveals the car is slow.

## Next steps

- Re-run the backtest as rounds are added — the model-vs-baseline gap is the
  number to watch
- Weight `hist_circuit_points` by the driver's current car competitiveness, so
  a strong record earned in a faster car stops inflating a weak team
- Investigate whether *any* feature predicts a single team's race-to-race
  swing, or whether that variance is mostly irreducible (reliability, weather,
  safety cars)
- Consider fixing the pagination issue above in the collector

## Author

Built as part of a data engineering / data science portfolio by a Computer
Engineering student.
