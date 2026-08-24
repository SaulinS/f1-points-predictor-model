"""
Previsões com o modelo treinado.

Faz duas coisas diferentes, e a distinção importa:

1. `--modo holdout`: refaz a previsão da última corrida já disputada, treinando
   só com o que veio antes dela. Serve para comparar previsão e resultado real
   -- é uma previsão de verdade, fora da amostra, só que sobre o passado.

2. `--modo proxima`: prevê a próxima corrida do calendário. Aqui existe uma
   limitação concreta: o qualifying dessa corrida ainda não aconteceu, então as
   features de grid não existem. O modelo usado neste modo é treinado sem elas
   (só forma, histórico do piloto no circuito e tipo de pista), e por isso é
   mais fraco que o do backtest. A formação assumida é a da corrida mais
   recente.

Uso:
    python -m src.models.predict --modo holdout
    python -m src.models.predict --modo proxima
"""

import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.etl.db import get_engine
from src.models.build_features import (
    FORM_WINDOW,
    TARGET_SEASON,
    fetch_driver_circuit_history,
)
from src.models.train import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    make_model,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

# Sem qualifying da próxima corrida, o modelo precisa viver só do que já é
# conhecido antes do fim de semana.
FORM_ONLY_FEATURES = [f for f in NUMERIC_FEATURES if not f.startswith("grid_")]

MODEL_KIND = "hurdle_rf"


def predict_holdout(df: pd.DataFrame) -> pd.DataFrame:
    """Prevê a última rodada disponível treinando apenas com as anteriores."""
    last_round = int(df["round"].max())
    train = df[df["round"] < last_round]
    test = df[df["round"] == last_round].copy()

    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    model = make_model(MODEL_KIND)
    model.fit(train[cols], train[TARGET])
    test["previsto"] = model.predict(test[cols])
    test["erro"] = test["previsto"] - test[TARGET]

    logger.info(f"Rodada prevista: {last_round} (treino: rodadas {train['round'].min()}-{last_round - 1}, {len(train)} linhas)")
    return test.sort_values(TARGET, ascending=False)


def build_next_race_features(conn, next_round: int, circuit_id: str) -> pd.DataFrame:
    """
    Monta a linha de features de cada equipe para uma corrida ainda não
    disputada, usando apenas informação já conhecida.
    """
    target = pd.read_sql(
        text("""
            SELECT round, constructor_id, team_points::float AS team_points, dnf_count
            FROM team_race_points WHERE season = :s
        """),
        conn, params={"s": TARGET_SEASON},
    )

    # A formação esperada é a da corrida mais recente -- sem qualifying da
    # próxima, é a melhor aproximação disponível.
    lineup = pd.read_sql(
        text("""
            SELECT q.constructor_id, q.driver_id
            FROM qualifying q
            JOIN races ra ON ra.race_id = q.race_id
            WHERE ra.season = :s
              AND ra.round = (SELECT MAX(round) FROM races WHERE season = :s)
        """),
        conn, params={"s": TARGET_SEASON},
    )

    track_type = pd.read_sql(
        text("SELECT track_type FROM circuits WHERE circuit_id = :c"),
        conn, params={"c": circuit_id},
    )["track_type"].iloc[0]

    history = fetch_driver_circuit_history(conn)
    hist_circuit = history[history["circuit_id"] == circuit_id]

    rows = []
    for team, g in target.groupby("constructor_id"):
        g = g.sort_values("round")
        drivers = lineup[lineup["constructor_id"] == team]["driver_id"]
        hist = hist_circuit[hist_circuit["driver_id"].isin(drivers)]["hist_avg_points"]

        rows.append({
            "round": next_round,
            "constructor_id": team,
            "circuit_id": circuit_id,
            "track_type": track_type,
            # Toda a temporada já disputada é passado em relação à próxima
            # corrida, então aqui não há shift a fazer.
            "form_last3": g["team_points"].tail(FORM_WINDOW).mean(),
            "form_todate": g["team_points"].mean(),
            "dnf_rate_todate": g["dnf_count"].mean(),
            "hist_circuit_points": hist.mean() if len(hist) else None,
        })
    return pd.DataFrame(rows)


def predict_next_race(df: pd.DataFrame) -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        calendar = pd.read_sql(
            text("SELECT MAX(round) AS last FROM races WHERE season = :s"),
            conn, params={"s": TARGET_SEASON},
        )
        next_round = int(calendar["last"].iloc[0]) + 1

        # O calendário completo vive no JSON bruto; o banco só tem corridas com
        # resultado. Lemos o circuito da próxima rodada de lá.
        raw_calendar = pd.read_json(
            Path(__file__).resolve().parents[2] / "data" / "raw" / "races" / f"{TARGET_SEASON}_calendar.json"
        )
        nxt = raw_calendar[raw_calendar["round"] == next_round].iloc[0]
        circuit_id = nxt["Circuit"]["circuitId"]
        race_name = nxt["raceName"]

        features = build_next_race_features(conn, next_round, circuit_id)

    # Treina sem as colunas de grid, já que elas não existirão na previsão.
    cols = FORM_ONLY_FEATURES + CATEGORICAL_FEATURES
    model = make_model(MODEL_KIND, numeric_features=FORM_ONLY_FEATURES)
    model.fit(df[cols], df[TARGET])
    features["previsto"] = model.predict(features[cols])

    logger.info(f"Prevendo rodada {next_round}: {race_name} ({circuit_id}), modelo sem features de grid")
    return features.sort_values("previsto", ascending=False), race_name, next_round


def main():
    parser = argparse.ArgumentParser(description="Previsões do modelo de pontos por equipe")
    parser.add_argument("--modo", choices=["holdout", "proxima"], default="holdout")
    args = parser.parse_args()

    df = pd.read_csv(PROCESSED_DIR / "team_race_features.csv")

    if args.modo == "holdout":
        out = predict_holdout(df)
        print("\n=== Previsão vs resultado real (última corrida disputada) ===")
        print(
            out[["constructor_id", TARGET, "previsto", "erro"]]
            .rename(columns={"constructor_id": "equipe", TARGET: "real"})
            .round(1).to_string(index=False)
        )
        print(f"\nMAE: {out['erro'].abs().mean():.2f}")
    else:
        out, race_name, rnd = predict_next_race(df)
        print(f"\n=== Previsão para a rodada {rnd}: {race_name} ===")
        print(
            out[["constructor_id", "previsto", "form_last3", "form_todate"]]
            .rename(columns={"constructor_id": "equipe"})
            .round(1).to_string(index=False)
        )
        print("\nAtenção: sem qualifying disputado, este modelo não usa features de grid.")


if __name__ == "__main__":
    main()
