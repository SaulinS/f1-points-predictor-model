"""
Pipeline de ETL: lê os JSONs brutos de data/raw/ e carrega no PostgreSQL.

Ordem de carga (respeita as dependências de chave estrangeira):
    1. circuits, drivers, constructors (dimensões, sem dependências)
    2. races (depende de circuits)
    3. results, qualifying, pitstops (dependem de races, drivers, constructors)

Roda em cima de dois conjuntos de dados:
    - Temporada 2026 (fonte principal, o alvo do modelo)
    - Histórico de pilotos por circuito 2019-2025 (fonte da feature de histórico)

Uso:
    python -m src.etl.load_to_postgres
"""

import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.etl.db import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
LOOKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "lookup"


def load_json(path: Path):
    if not path.exists():
        logger.warning(f"Arquivo não encontrado, pulando: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_track_types() -> dict:
    """Lê o CSV curado manualmente e retorna {circuit_id: track_type}."""
    path = LOOKUP_DIR / "track_types.csv"
    if not path.exists():
        logger.warning(f"track_types.csv não encontrado em {path} -- track_type ficará NULL")
        return {}
    import csv
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["circuit_id"]: row["track_type"] for row in reader}


def safe_int(value):
    """Converte para int com segurança -- retorna None para valores vazios, nulos ou não-numéricos."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def upsert_circuit(conn, circuit: dict, track_types: dict):
    conn.execute(text("""
        INSERT INTO circuits (circuit_id, circuit_name, track_type, country, locality, latitude, longitude)
        VALUES (:id, :name, :track_type, :country, :locality, :lat, :long)
        ON CONFLICT (circuit_id) DO NOTHING
    """), {
        "id": circuit["circuitId"],
        "name": circuit["circuitName"],
        "track_type": track_types.get(circuit["circuitId"]),
        "country": circuit["Location"]["country"],
        "locality": circuit["Location"]["locality"],
        "lat": float(circuit["Location"]["lat"]),
        "long": float(circuit["Location"]["long"]),
    })


def upsert_driver(conn, driver: dict):
    conn.execute(text("""
        INSERT INTO drivers (driver_id, driver_code, given_name, family_name, nationality)
        VALUES (:id, :code, :given, :family, :nat)
        ON CONFLICT (driver_id) DO NOTHING
    """), {
        "id": driver["driverId"],
        "code": driver.get("code"),
        "given": driver["givenName"],
        "family": driver["familyName"],
        "nat": driver.get("nationality"),
    })


def upsert_constructor(conn, constructor: dict):
    conn.execute(text("""
        INSERT INTO constructors (constructor_id, name, nationality)
        VALUES (:id, :name, :nat)
        ON CONFLICT (constructor_id) DO NOTHING
    """), {
        "id": constructor["constructorId"],
        "name": constructor["name"],
        "nat": constructor.get("nationality"),
    })


def upsert_race(conn, race: dict) -> int:
    """Insere a corrida (se não existir) e retorna o race_id."""
    result = conn.execute(text("""
        INSERT INTO races (season, round, circuit_id, race_name, race_date)
        VALUES (:season, :round, :circuit_id, :name, :date)
        ON CONFLICT (season, round) DO UPDATE SET race_name = EXCLUDED.race_name
        RETURNING race_id
    """), {
        "season": int(race["season"]),
        "round": int(race["round"]),
        "circuit_id": race["Circuit"]["circuitId"],
        "name": race["raceName"],
        "date": race["date"],
    })
    return result.scalar()


def get_race_id(conn, season: int, round_: int):
    result = conn.execute(text("""
        SELECT race_id FROM races WHERE season = :season AND round = :round
    """), {"season": season, "round": round_})
    row = result.fetchone()
    return row[0] if row else None


def insert_result(conn, race_id: int, result: dict):
    conn.execute(text("""
        INSERT INTO results (race_id, driver_id, constructor_id, grid, position, points, status, laps)
        VALUES (:race_id, :driver_id, :constructor_id, :grid, :position, :points, :status, :laps)
        ON CONFLICT (race_id, driver_id) DO NOTHING
    """), {
        "race_id": race_id,
        "driver_id": result["Driver"]["driverId"],
        "constructor_id": result["Constructor"]["constructorId"],
        "grid": safe_int(result.get("grid")),
        "position": safe_int(result.get("position")),
        "points": float(result.get("points", 0)),
        "status": result.get("status"),
        "laps": safe_int(result.get("laps")),
    })


def process_race_block(conn, race: dict, track_types: dict):
    """
    Processa um objeto 'race' no formato padrão da API (usado tanto pelos
    resultados de 2026 quanto pelo histórico de pilotos), inserindo circuito,
    corrida, pilotos, equipes e resultados.
    """
    upsert_circuit(conn, race["Circuit"], track_types)
    race_id = upsert_race(conn, race)

    for result in race.get("Results", []):
        upsert_driver(conn, result["Driver"])
        upsert_constructor(conn, result["Constructor"])
        insert_result(conn, race_id, result)

    return race_id


def load_season_results(conn, track_types: dict):
    """Carrega circuits, races, drivers, constructors e results da temporada 2026."""
    data = load_json(RAW_DIR / "races" / "2026_results.json")
    if not data:
        return

    count = 0
    for race in data:
        process_race_block(conn, race, track_types)
        count += 1
    logger.info(f"[results 2026] {count} corridas processadas")


def load_qualifying(conn):
    data = load_json(RAW_DIR / "qualifying" / "2026_qualifying.json")
    if not data:
        return

    count = 0
    for race in data:
        race_id = get_race_id(conn, int(race["season"]), int(race["round"]))
        if race_id is None:
            logger.warning(f"Corrida não encontrada para qualifying: {race['season']} R{race['round']}")
            continue

        for q in race.get("QualifyingResults", []):
            upsert_driver(conn, q["Driver"])
            upsert_constructor(conn, q["Constructor"])
            conn.execute(text("""
                INSERT INTO qualifying (race_id, driver_id, constructor_id, position, q1_time, q2_time, q3_time)
                VALUES (:race_id, :driver_id, :constructor_id, :position, :q1, :q2, :q3)
                ON CONFLICT (race_id, driver_id) DO NOTHING
            """), {
                "race_id": race_id,
                "driver_id": q["Driver"]["driverId"],
                "constructor_id": q["Constructor"]["constructorId"],
                "position": safe_int(q.get("position")),
                "q1": q.get("Q1"),
                "q2": q.get("Q2"),
                "q3": q.get("Q3"),
            })
            count += 1
    logger.info(f"[qualifying] {count} registros processados")


def parse_duration_ms(duration: str):
    """Converte duração tipo '23.456' (segundos) para milissegundos. Retorna None se inválido."""
    if not duration:
        return None
    try:
        return int(float(duration) * 1000)
    except (ValueError, TypeError):
        return None


def load_pitstops(conn):
    data = load_json(RAW_DIR / "pitstops" / "2026_pitstops.json")
    if not data:
        return

    count = 0
    for round_str, stops in data.items():
        race_id = get_race_id(conn, 2026, int(round_str))
        if race_id is None:
            logger.warning(f"Corrida não encontrada para pitstops: round {round_str}")
            continue

        for stop in stops:
            conn.execute(text("""
                INSERT INTO pitstops (race_id, driver_id, stop_number, lap, stop_time, duration_ms)
                VALUES (:race_id, :driver_id, :stop_number, :lap, :stop_time, :duration_ms)
                ON CONFLICT (race_id, driver_id, stop_number) DO NOTHING
            """), {
                "race_id": race_id,
                "driver_id": stop["driverId"],
                "stop_number": safe_int(stop["stop"]),
                "lap": safe_int(stop.get("lap")),
                "stop_time": stop.get("time"),
                "duration_ms": parse_duration_ms(stop.get("duration")),
            })
            count += 1
    logger.info(f"[pitstops] {count} registros processados")


def load_driver_circuit_history(conn, track_types: dict):
    """
    Carrega o histórico 2019-2025 (data/raw/driver_history/driver_circuit_history.json).
    Formato: {driver_id: {circuit_id: [race objects...]}}
    """
    data = load_json(RAW_DIR / "driver_history" / "driver_circuit_history.json")
    if not data:
        return

    count = 0
    for driver_id, circuits in data.items():
        for circuit_id, races in circuits.items():
            for race in races:
                process_race_block(conn, race, track_types)
                count += 1
    logger.info(f"[driver_circuit_history] {count} corridas históricas processadas")


def main():
    track_types = load_track_types()
    engine: Engine = get_engine()

    with engine.begin() as conn:
        logger.info("Iniciando ETL...")
        load_season_results(conn, track_types)
        load_qualifying(conn)
        load_pitstops(conn)
        load_driver_circuit_history(conn, track_types)
        logger.info("ETL concluído com sucesso.")


if __name__ == "__main__":
    main()
