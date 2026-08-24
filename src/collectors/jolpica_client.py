"""
Cliente para a API Jolpica-F1 (sucessora da Ergast).
Documentação: https://github.com/jolpica/jolpica-f1/blob/main/docs/README.md

Implementa:
- Rate limiting simples (para não sermos bloqueados pela API pública)
- Retry com backoff exponencial em caso de falha de rede
- Paginação automática (a API limita a 30 resultados por página por padrão)
- Cache local em disco (raw layer) para não reconsultar dados já baixados
"""

import time
import json
import logging
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api.jolpi.ca/ergast/f1"
RAW_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# Rate limiting conservador: a API pede para respeitarmos limites de uso justo.
# Preferimos ser mais lentos e confiáveis do que rápidos e bloqueados.
MIN_SECONDS_BETWEEN_REQUESTS = 0.5
MAX_RETRIES = 5
PAGE_LIMIT = 100  # a API aceita até 100 por página via parâmetro 'limit'


class JolpicaClient:
    def __init__(self, base_url: str = BASE_URL, cache_dir: Path = RAW_DATA_DIR):
        self.base_url = base_url
        self.cache_dir = cache_dir
        self._last_request_time = 0.0
        self.session = requests.Session()

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        wait = MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.time()

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = params or {}
        params.setdefault("limit", PAGE_LIMIT)

        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    # A API manda o header Retry-After dizendo quanto tempo esperar.
                    # Se não vier, usamos um backoff bem mais generoso que antes --
                    # o limite sustentado é por HORA, então esperar poucos segundos
                    # não resolve se o problema for o teto de 500/hora.
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after else 60 * attempt
                    logger.warning(
                        f"Rate limit atingido (429). Aguardando {wait_time}s antes de tentar de novo..."
                    )
                    time.sleep(wait_time)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                logger.warning(f"Tentativa {attempt}/{MAX_RETRIES} falhou para {url}: {e}")
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Falha ao buscar {url} após {MAX_RETRIES} tentativas")

    def get_paginated(self, endpoint: str, table_key: str, list_key: str) -> list:
        """
        Busca todas as páginas de um endpoint que retorna listas (ex: resultados de temporada).

        table_key: chave do objeto tabela na resposta (ex: 'RaceTable', 'StandingsTable')
        list_key: chave da lista dentro da tabela (ex: 'Races')
        """
        offset = 0
        all_items = []

        while True:
            data = self._get(endpoint, params={"limit": PAGE_LIMIT, "offset": offset})
            mrdata = data["MRData"]
            table = mrdata[table_key]
            items = table.get(list_key, [])
            all_items.extend(items)

            total = int(mrdata["total"])
            offset += PAGE_LIMIT
            if offset >= total:
                break

        return all_items

    def save_raw(self, subfolder: str, filename: str, data):
        """Salva a resposta bruta em disco antes de qualquer tratamento (raw layer)."""
        out_dir = self.cache_dir / subfolder
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{filename}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Salvo: {out_path}")
        return out_path
