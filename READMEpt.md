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
- [~] **Fase 3 — Modelo preditivo**: pipeline de features e backtest de janela
      expansiva sem vazamento já implementados; os primeiros modelos batem os
      baselines ingênuos, embora ainda não por uma margem estatisticamente
      conclusiva (veja [Resultados da modelagem](#resultados-da-modelagem))
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

## Resultados da modelagem

```bash
python -m src.models.build_features   # banco -> data/processed/team_race_features.csv
python -m src.models.train            # backtest de janela expansiva
```

**As features são estritamente pré-corrida.** A formação da equipe e o grid
vêm da tabela `qualifying` (sábado), não de `results` — assim a tabela de
resultados serve só para montar o alvo, e nenhum dado de chegada consegue
vazar para uma feature por descuido. As features de forma (`form_last3`,
`form_todate`, `dnf_rate_todate`) são deslocadas em uma rodada, então a
corrida sendo prevista nunca entra no cálculo da própria feature. Verificado
programaticamente: 0 linhas em que a corrida corrente vaza para suas features.

**A validação é um backtest de janela expansiva**: para cada rodada de teste,
o modelo treina apenas com as rodadas anteriores. Um k-fold aleatório
treinaria com corridas futuras para prever corridas passadas, inflando a
métrica de um jeito que nunca se sustenta em uso real.

Backtest nas rodadas 6-12 (77 previsões por modelo):

| Modelo | MAE | RMSE | Spearman intra-corrida |
|---|---|---|---|
| Random Forest | **3,75** | 5,57 | **0,871** |
| Ridge | 4,06 | **5,56** | 0,864 |
| Baseline: média da equipe até a rodada | 4,42 | 6,38 | 0,819 |
| Baseline: última corrida da equipe | 4,96 | 7,80 | 0,835 |
| Baseline: média global | 9,73 | 11,22 | — |

**Leitura honesta desses números.** O Random Forest bate o baseline mais forte
por 0,67 de MAE e vence em 6 das 7 rodadas de teste, mas um bootstrap pareado
coloca o IC95% desse ganho em **[-0,12, +1,46] — ou seja, cruza o zero**.
A vantagem é sugestiva (P(melhor) ≈ 0,95), não conclusiva. Esse é o resultado
esperado com 121 linhas: a F1 dá ~11 equipes × ~23 corridas por temporada, e
restringir ao regulamento 2026 limita muito o volume de dados. A diferença
tende a ficar decidível conforme a temporada avança.

Os coeficientes do Ridge fazem sentido físico, o que é um bom sinal de que a
pipeline não está ajustando ruído: a forma na temporada domina (+3,90),
grids melhores (mais baixos) elevam a previsão de pontos (-2,09 em
`grid_best`), e o tipo de pista quase não contribui (|coef| < 0,04) — com 5
categorias em 121 linhas não há dados suficientes para aprender efeito de
pista.

## Próximos passos

- Rodar o backtest de novo conforme as rodadas avançam — a diferença entre RF
  e baseline é o número a acompanhar
- Testar um alvo em duas etapas (pontuou / quanto pontuou), dado quantas
  linhas são exatamente 0
- Considerar corrigir o problema de paginação descrito acima no coletor

## Autor

Construído como parte de um portfólio de engenharia de dados / data science
por um estudante de Engenharia da Computação.
