"""
Conexão com o PostgreSQL. Usa os mesmos valores default do docker-compose.yml
-- se você mudou usuário/senha/porta no compose, ajuste aqui ou via variáveis
de ambiente (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT).
"""

import os
from sqlalchemy import create_engine

POSTGRES_USER = os.getenv("POSTGRES_USER", "f1_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "f1_dev_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "f1_predictor")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)


def get_engine():
    return create_engine(DATABASE_URL)
