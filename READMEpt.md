# F1 Team Points Predictor

[🇺🇸 English](README.md) | 🇧🇷 Português

Pipeline de dados end-to-end (coleta → engenharia de dados → modelo preditivo)
para prever a **pontuação de uma equipe de F1 por corrida**, usando dados
exclusivamente da era de regulamento técnico atual (2026).

Projeto de portfólio construído durante o recesso do semestre, com foco em
práticas sólidas de engenharia de dados: coleta resiliente com rate limiting,
armazenamento em camadas (raw → processed), banco de dados relacional
containerizado, e uma pipeline reproduzível.

## Por que só 2026?

A temporada 2026 de F1 introduziu um regulamento técnico totalmente novo
(motor híbrido, aerodinâmica ativa, novas equipes). Misturar dados de eras de
regulamento diferentes distorceria o modelo, já que a performance relativa
entre equipes não é comparável entre regulamentos. Por isso, a variável-alvo
(pontos da equipe) é treinada **exclusivamente** com dados de 2026. Features
baseadas em características fixas — como o histórico de um piloto num
circuito — ainda usam dados históricos (2019-2025), já que dependem da
habilidade do piloto, não do carro.

## Status do projeto

- [x] **Fase 1 — Coleta de Dados**: calendário, resultados de corrida,
      qualifying, pit stops, status de corrida, grid atual e histórico de
      pilotos por circuito
- [x] **Fase 2 — Engenharia de Dados**: schema relacional, banco PostgreSQL
      containerizado com Docker, e pipeline de ETL (raw → banco) — **rodada e
      verificada contra um Postgres real** (não só em dry-run)
- [ ] Fase 3 — Modelo preditivo (regressão de pontos por corrida)
- [ ] Fase 4 — Dashboard ou API servindo as previsões

Os dados atualmente cobrem a temporada 2026 até a **rodada 12**, coletados em
24/08/2026.

## Stack técnica

| Camada | Tecnologia |
|---|---|
| Coleta de dados | Python, `requests` |
| Armazenamento raw | JSON (camada raw) |
| Banco de dados | PostgreSQL 16 (via Docker) |
| ETL | Python, `pandas`, `sqlalchemy` |
| Modelagem | `scikit-learn` (planejado) |
| Ambiente | WSL2 (Ubuntu) + Docker Desktop |

## Fontes de dados

- **[Jolpica-F1](https://api.jolpi.ca)** — API pública, sucessora da Ergast
  API, fornecendo resultados de corrida, qualifying, pit stops, status de
  finalização e classificações históricas e da temporada atual.
- **Classificação de tipo de pista** — curada manualmente
  (`data/lookup/track_types.csv`), já que não existe fonte pública
  estruturada para essa categorização. Validada contra os `circuit_id` reais
  retornados pela API — todos batem, exceto `madring`, um circuito novo em
  2026 que ainda não sediou corrida.

## Estrutura do projeto

```
f1-team-points-predictor/
├── data/
│   ├── raw/              # dados brutos, exatamente como vieram da API
│   ├── processed/        # dados tratados, prontos para carga no banco
│   └── lookup/           # tabelas de referência curadas manualmente
├── src/
│   ├── collectors/       # scripts de coleta de dados (Fase 1)
│   ├── etl/               # schema.sql e pipeline de transformação/carga (Fase 2)
│   └── models/             # treinamento e avaliação do modelo (Fase 3)
├── docker-compose.yml        # sobe o container do PostgreSQL
└── requirements.txt
```

## Como rodar

**Pré-requisitos:** WSL2 (Ubuntu) com Python 3.10+, Docker Desktop com
integração WSL2 ativada.

```bash
# Ambiente Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Banco de dados
docker compose up -d

# Coleta de dados (Fase 1)
python -m src.collectors.collect_season --season 2026
python -m src.collectors.collect_current_grid --season 2026
python -m src.collectors.collect_driver_circuit_history --seasons 2019 2020 2021 2022 2023 2024 2025

# ETL (Fase 2)
python -m src.etl.load_to_postgres
```

Os dados brutos são salvos em `data/raw/`. O schema do banco é criado
automaticamente na primeira vez que o container do PostgreSQL sobe (via
`docker-entrypoint-initdb.d`).

## Design do banco de dados

O banco tem duas views centrais que evitam duplicar dados brutos:

- `team_race_points` — soma os pontos dos dois pilotos por equipe/corrida
  (esse é o **alvo** do modelo preditivo)
- `driver_circuit_history` — resultados de temporadas anteriores por piloto e
  circuito (essa é a **feature** de histórico do piloto na pista)

Veja `src/etl/schema.sql` para o schema completo.

## Issue conhecida: blocos de corrida duplicados no dado bruto paginado

O endpoint `/results/` da Jolpica-F1 pagina por **resultado individual**, não
por corrida. Como cada corrida tem ~20-22 resultados e as páginas são
buscadas em lotes de 100, uma corrida pode cair na fronteira de duas páginas
e aparecer como dois blocos parciais separados no JSON bruto (ex: a rodada 5
como 12+10 resultados, a rodada 10 como 2+20). Isso não corrompe o banco —
`load_to_postgres.py` faz upsert por `(race_id, driver_id)`, então os dois
blocos parciais juntos ainda produzem o conjunto correto e completo de
resultados — mas significa que não se deve assumir um bloco por corrida no
JSON bruto. Vale corrigir no coletor (ex: remontar os blocos divididos, ou
paginar por corrida em vez de por resultado) antes de confiar em
`data/raw/races/*.json` para qualquer uso fora desse ETL.

## Próximos passos (Fase 3)

- Definir as features de treino (histórico do piloto por circuito, tipo de
  pista, etc.)
- Treinar e avaliar o modelo preditivo
- Considerar corrigir o problema de paginação descrito acima no coletor

## Autor

Construído como parte de um portfólio de engenharia de dados / data science
por um estudante de Engenharia da Computação.
