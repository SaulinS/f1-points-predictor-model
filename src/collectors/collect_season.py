"""
Coleta os dados da temporada 2026 de F1 (regulamento atual).

Uso:
    python -m src.collectors.collect_season --season 2026

Salva tudo em data/raw/ em formato JSON bruto, um arquivo por tipo de dado.
Não faz nenhum tratamento/limpeza aqui -- isso é responsabilidade da fase de ETL.
"""

import argparse
import logging

from src.collectors.jolpica_client import JolpicaClient

logger = logging.getLogger(__name__)


def collect_races(client: JolpicaClient, season: int):
    """Calendário de corridas da temporada."""
    races = client.get_paginated(f"{season}/races/", "RaceTable", "Races")
    client.save_raw("races", f"{season}_calendar", races)
    logger.info(f"{len(races)} corridas encontradas para {season}")
    return races


def collect_results(client: JolpicaClient, season: int):
    """Resultados de corrida (posição final, pontos, status)."""
    results = client.get_paginated(f"{season}/results/", "RaceTable", "Races")
    client.save_raw("races", f"{season}_results", results)
    return results


def collect_qualifying(client: JolpicaClient, season: int):
    """Grid de largada (resultado da classificação)."""
    qualifying = client.get_paginated(f"{season}/qualifying/", "RaceTable", "Races")
    client.save_raw("qualifying", f"{season}_qualifying", qualifying)
    return qualifying


def collect_pitstops(client: JolpicaClient, season: int, rounds: list):
    """Pit stops por corrida (precisa iterar round a round)."""
    all_pitstops = {}
    for round_number in rounds:
        endpoint = f"{season}/{round_number}/pitstops/"
        data = client._get(endpoint)
        races = data["MRData"]["RaceTable"]["Races"]
        pitstops = races[0]["PitStops"] if races else []
        all_pitstops[round_number] = pitstops
    client.save_raw("pitstops", f"{season}_pitstops", all_pitstops)
    return all_pitstops


def collect_status(client: JolpicaClient, season: int):
    """Status de finalização (DNF, acidente, etc.) -- usado para confiabilidade da equipe."""
    status = client.get_paginated(f"{season}/status/", "StatusTable", "Status")
    client.save_raw("status", f"{season}_status", status)
    return status


def collect_constructor_standings(client: JolpicaClient, season: int):
    """Classificação de construtores por rodada -- útil para validar o target do modelo."""
    standings = client.get_paginated(
        f"{season}/constructorstandings/", "StandingsTable", "StandingsLists"
    )
    client.save_raw("races", f"{season}_constructor_standings", standings)
    return standings


def main():
    parser = argparse.ArgumentParser(description="Coleta dados de uma temporada de F1")
    parser.add_argument("--season", type=int, default=2026, help="Ano da temporada")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    client = JolpicaClient()

    logger.info(f"Iniciando coleta da temporada {args.season}")

    races = collect_races(client, args.season)
    collect_results(client, args.season)
    collect_qualifying(client, args.season)
    collect_status(client, args.season)
    collect_constructor_standings(client, args.season)

    rounds = [int(r["round"]) for r in races]
    collect_pitstops(client, args.season, rounds)

    logger.info("Coleta concluída.")


if __name__ == "__main__":
    main()
