"""
Coleta o histórico de desempenho de cada piloto do grid 2026 nos circuitos do
calendário atual, olhando temporadas anteriores. Alimenta a feature "histórico
do piloto na pista".

ESTRATÉGIA DE REQUISIÇÕES (importante): em vez de fazer uma chamada por par
piloto+circuito (o que geraria ~pilotos x circuitos requisições e estouraria
o limite de 500/hora da API), fazemos UMA chamada paginada por piloto,
buscando toda a carreira dele, e filtramos localmente (em Python) por circuito
e por temporada. Isso reduz o total para ~1-3 requisições por piloto
(dependendo de quantas páginas a carreira dele ocupa).

Importante sobre a escolha de usar dados de temporadas passadas: isso é
aceitável aqui porque a feature é sobre o PILOTO na pista (habilidade,
adaptação ao traçado), não sobre o desempenho do CARRO/EQUIPE -- que é onde
o regulamento 2026 realmente importa e onde restringimos aos dados atuais.

Uso:
    python -m src.collectors.collect_driver_circuit_history --seasons 2019 2020 2021 2022 2023 2024 2025
"""

import argparse
import json
import logging

from src.collectors.jolpica_client import JolpicaClient, RAW_DATA_DIR

logger = logging.getLogger(__name__)

CHECKPOINT_PATH = RAW_DATA_DIR / "driver_history" / "driver_circuit_history.json"


def get_2026_circuits(client: JolpicaClient) -> set:
    races = client.get_paginated("2026/races/", "RaceTable", "Races")
    return {r["Circuit"]["circuitId"] for r in races}


def get_2026_drivers(client: JolpicaClient) -> list:
    drivers = client.get_paginated("2026/drivers/", "DriverTable", "Drivers")
    return [d["driverId"] for d in drivers]


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Checkpoint encontrado: {len(data)} pilotos já coletados.")
        return data
    return {}


def save_checkpoint(history: dict):
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def collect_history(client: JolpicaClient, seasons: list):
    circuits = get_2026_circuits(client)
    drivers = get_2026_drivers(client)

    logger.info(f"{len(drivers)} pilotos, filtrando para {len(circuits)} circuitos do calendário 2026")

    history = load_checkpoint()

    for driver_id in drivers:
        if driver_id in history:
            logger.info(f"Pulando {driver_id} (já coletado)")
            continue

        all_races = client.get_paginated(
            f"drivers/{driver_id}/results/", "RaceTable", "Races"
        )

        relevant = [
            r for r in all_races
            if r["Circuit"]["circuitId"] in circuits and int(r["season"]) in seasons
        ]

        by_circuit = {}
        for race in relevant:
            circuit_id = race["Circuit"]["circuitId"]
            by_circuit.setdefault(circuit_id, []).append(race)

        history[driver_id] = by_circuit
        save_checkpoint(history)

        logger.info(f"{driver_id}: {len(relevant)} resultados relevantes em {len(by_circuit)} circuitos")

    logger.info(f"Concluído. {len(history)} pilotos no total.")
    return history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seasons", type=int, nargs="+", default=[2019, 2020, 2021, 2022, 2023, 2024, 2025]
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    client = JolpicaClient()

    try:
        collect_history(client, args.seasons)
    except Exception as e:
        logger.error(
            f"Execução interrompida por erro: {e}. "
            "O progresso foi salvo por piloto -- rode de novo para continuar de onde parou."
        )
        raise


if __name__ == "__main__":
    main()
