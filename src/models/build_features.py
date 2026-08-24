"""
Construção da tabela de features para o modelo de pontos por equipe/corrida.

Regra central deste módulo: **nenhuma feature pode usar informação que só
existe depois da largada**. O alvo (pontos da equipe na corrida) é o que
queremos prever, então tudo que descreve o que aconteceu durante a corrida
-- posição final, DNF daquela corrida, pit stops daquela corrida -- está
proibido como feature.

Por isso a formação da equipe e o grid vêm da tabela `qualifying` (sábado,
antes da corrida) e não de `results`: assim a tabela de resultados é usada
exclusivamente para montar o alvo, e não há como um dado de chegada vazar
para dentro das features por descuido.

As features de forma da equipe (média de pontos recentes, confiabilidade)
usam o histórico do próprio alvo, o que é legítimo em série temporal desde
que deslocado em uma rodada -- `shift(1)` garante que a corrida sendo
prevista nunca entra no cálculo da própria feature.

Uso:
    python -m src.models.build_features
"""

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.etl.db import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
TARGET_SEASON = 2026

# Janela da média móvel de forma recente. 3 corridas é um meio-termo entre
# capturar evolução de desenvolvimento do carro e não virar ruído puro.
FORM_WINDOW = 3


def fetch_grid(conn) -> pd.DataFrame:
    """
    Formação e grid de largada por equipe/corrida, a partir do qualifying.

    Uma equipe tem dois carros, então resumimos as duas posições em duas
    features: a melhor (quão perto da frente a equipe conseguiu colocar
    pelo menos um carro) e a média (força geral da dupla naquele fim de
    semana).
    """
    sql = text("""
        SELECT
            ra.race_id,
            ra.round,
            ra.circuit_id,
            c.track_type,
            q.constructor_id,
            q.driver_id,
            q.position AS grid_pos
        FROM qualifying q
        JOIN races ra ON ra.race_id = q.race_id
        JOIN circuits c ON c.circuit_id = ra.circuit_id
        WHERE ra.season = :season
    """)
    return pd.read_sql(sql, conn, params={"season": TARGET_SEASON})


def fetch_target(conn) -> pd.DataFrame:
    """Alvo do modelo: pontos somados da equipe em cada corrida de 2026."""
    sql = text("""
        SELECT race_id, round, circuit_id, constructor_id, team_points, dnf_count
        FROM team_race_points
        WHERE season = :season
    """)
    df = pd.read_sql(sql, conn, params={"season": TARGET_SEASON})
    df["team_points"] = df["team_points"].astype(float)
    return df


def fetch_driver_circuit_history(conn) -> pd.DataFrame:
    """
    Desempenho histórico (2019-2025) de cada piloto em cada circuito.

    Essa é a única feature que olha para fora de 2026. Ela é defensável
    porque mede habilidade do piloto naquela pista -- algo que não depende
    do regulamento do carro -- e porque todos os dados são de temporadas
    anteriores, então não há vazamento sobre a corrida de 2026 em questão.
    """
    sql = text("""
        SELECT
            driver_id,
            circuit_id,
            AVG(points) AS hist_avg_points,
            COUNT(*)    AS hist_races
        FROM driver_circuit_history
        GROUP BY driver_id, circuit_id
    """)
    df = pd.read_sql(sql, conn)
    df["hist_avg_points"] = df["hist_avg_points"].astype(float)
    return df


def build_team_race_frame(grid: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """
    Colapsa o nível piloto/corrida para equipe/corrida, que é a granularidade
    do alvo.
    """
    # Histórico entra no nível do piloto e só depois é agregado por equipe,
    # para que a feature represente "a dupla que esta equipe vai colocar na
    # pista tem que histórico aqui?".
    grid = grid.merge(history, on=["driver_id", "circuit_id"], how="left")

    agg = (
        grid.groupby(["race_id", "round", "circuit_id", "track_type", "constructor_id"], as_index=False)
        .agg(
            grid_best=("grid_pos", "min"),
            grid_mean=("grid_pos", "mean"),
            hist_circuit_points=("hist_avg_points", "mean"),
        )
    )
    return agg


def add_form_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Features de forma da equipe, calculadas apenas com rodadas ANTERIORES.

    O `shift(1)` dentro de cada equipe é o que separa uma feature legítima de
    vazamento: sem ele, a média "até agora" incluiria os pontos da corrida que
    estamos tentando prever, e o modelo pareceria excelente por motivos que não
    se sustentam numa previsão real.
    """
    df = df.sort_values(["constructor_id", "round"]).copy()
    by_team = df.groupby("constructor_id", sort=False)

    prev_points = by_team["team_points"].shift(1)
    prev_dnf = by_team["dnf_count"].shift(1)

    # Reagrupa sobre a série já deslocada: a janela passa a enxergar apenas o
    # passado, nunca a corrida corrente.
    df["form_last3"] = prev_points.groupby(df["constructor_id"], sort=False).transform(
        lambda s: s.rolling(FORM_WINDOW, min_periods=1).mean()
    )
    df["form_todate"] = prev_points.groupby(df["constructor_id"], sort=False).transform(
        lambda s: s.expanding(min_periods=1).mean()
    )
    df["dnf_rate_todate"] = prev_dnf.groupby(df["constructor_id"], sort=False).transform(
        lambda s: s.expanding(min_periods=1).mean()
    )

    return df.sort_values(["round", "constructor_id"]).reset_index(drop=True)


def main():
    engine = get_engine()
    with engine.connect() as conn:
        grid = fetch_grid(conn)
        target = fetch_target(conn)
        history = fetch_driver_circuit_history(conn)

    logger.info(
        f"Base bruta: {len(grid)} linhas de qualifying, {len(target)} linhas de alvo, "
        f"{len(history)} pares piloto/circuito no histórico"
    )

    features = build_team_race_frame(grid, history)

    # O alvo manda na granularidade final: uma linha por equipe/corrida.
    df = target.merge(
        features,
        on=["race_id", "round", "circuit_id", "constructor_id"],
        how="left",
    )
    df = add_form_features(df)

    # A rodada 1 não tem passado para as features de forma, então sai da base
    # de modelagem. É uma perda pequena (11 linhas) e evita ter que inventar
    # um valor inicial arbitrário que o modelo trataria como informação real.
    before = len(df)
    df = df[df["form_todate"].notna()].reset_index(drop=True)
    logger.info(f"Removidas {before - len(df)} linhas sem histórico de forma (rodada 1)")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "team_race_features.csv"
    df.to_csv(out_path, index=False)

    logger.info(f"Tabela final: {len(df)} linhas, rodadas {df['round'].min()}-{df['round'].max()}")
    logger.info(f"Valores ausentes por coluna:\n{df.isna().sum()[lambda s: s > 0]}")
    logger.info(f"Salvo: {out_path}")


if __name__ == "__main__":
    main()
