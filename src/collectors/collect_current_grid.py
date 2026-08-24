"""
Coleta a lista de pilotos que estão atualmente no grid de 2026, já vinculados
à equipe que estão correndo. Usa o endpoint de driverstandings, porque ele
reflete quem de fato pontuou/correu na temporada (mais confiável do que
/drivers/, que pode incluir reservas ou substituições pontuais).

Gera:
- data/raw/circuits/2026_current_grid.json  (dado bruto, como veio da API)
- data/lookup/current_grid.csv              (tabela limpa, pronta pra uso)

Uso:
    python -m src.collectors.collect_current_grid --season 2026
"""

import argparse
import csv
import logging

from src.collectors.jolpica_client import JolpicaClient

logger = logging.getLogger(__name__)


def collect_current_grid(client: JolpicaClient, season: int):
    data = client._get(f"{season}/driverstandings/")
    standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]

    if not standings_lists:
        logger.warning(
            "Nenhuma standing encontrada -- a temporada pode não ter corridas "
            "suficientes ainda para gerar classificação."
        )
        return []

    driver_standings = standings_lists[0]["DriverStandings"]

    client.save_raw("circuits", f"{season}_current_grid", driver_standings)

    grid = []
    for entry in driver_standings:
        driver = entry["Driver"]
        constructor = entry["Constructors"][-1]
        grid.append({
            "driver_id": driver["driverId"],
            "driver_code": driver.get("code", ""),
            "given_name": driver["givenName"],
            "family_name": driver["familyName"],
            "nationality": driver["nationality"],
            "constructor_id": constructor["constructorId"],
            "constructor_name": constructor["name"],
            "points_so_far": entry["points"],
            "wins_so_far": entry["wins"],
        })

    return grid


def save_lookup_csv(grid: list, path: str):
    fieldnames = [
        "driver_id", "driver_code", "given_name", "family_name",
        "nationality", "constructor_id", "constructor_name",
        "points_so_far", "wins_so_far",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(grid)
    logger.info(f"Lookup salvo em: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    client = JolpicaClient()

    grid = collect_current_grid(client, args.season)
    logger.info(f"{len(grid)} pilotos encontrados no grid atual de {args.season}")

    for p in grid:
        logger.info(f"  {p['driver_code'] or p['driver_id']:>4} - {p['given_name']} {p['family_name']} ({p['constructor_name']})")

    save_lookup_csv(grid, "data/lookup/current_grid.csv")


if __name__ == "__main__":
    main()
