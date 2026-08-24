# F1 Team Points Predictor

Projeto de portfólio: pipeline de dados end-to-end (coleta → engenharia de dados →
modelo preditivo) para prever a **pontuação de uma equipe de F1 por corrida**,
usando dados do regulamento atual (2026).

## Motivação

2026 é um ano de regulamento totalmente novo na F1 (motor, aerodinâmica ativa,
novas equipes). Por isso, o modelo é treinado **apenas com dados de 2026** para
a variável-alvo (pontos da equipe), evitando misturar eras de regulamento
incomparáveis. Features sobre características fixas (tipo de pista, histórico
do piloto) podem usar dados históricos, já que não dependem do regulamento do carro.

## Status do projeto

- [x] Fase 1 — Coleta de Dados
- [x] Fase 2 — Engenharia de Dados (ETL, banco de dados, Docker) — schema, ETL e
  docker-compose implementados; ETL validado em dry-run contra os dados reais
  coletados (0 erros). **Falta rodar contra um Postgres real** para confirmar
  constraints/tipos em runtime.
- [ ] Fase 3 — Modelo Preditivo
- [ ] Fase 4 — Dashboard / API de entrega

## Estrutura

```
f1-team-points-predictor/
├── data/
│   ├── raw/            # dados brutos, exatamente como vieram da API (nunca editar manualmente)
│   ├── processed/       # dados tratados, prontos para modelagem
│   └── lookup/          # tabelas de referência curadas manualmente (ex: tipo de pista)
├── src/
│   ├── collectors/      # scripts de coleta de dados (Fase 1)
│   ├── etl/              # limpeza, transformação, carga no banco (Fase 2)
│   └── models/           # treinamento e avaliação do modelo (Fase 3)
├── notebooks/            # exploração e prototipagem
├── docker/                # configuração de containers (Fase 2)
└── requirements.txt
```

## Fonte de dados

- **Jolpica-F1 API** (https://api.jolpi.ca) — sucessora oficial da Ergast API.
  Fornece resultados de corrida, qualifying, pit stops, status de finalização
  e classificações.
- **Tipo de pista** — classificação manual em `data/lookup/track_types.csv`
  (não existe API pública para isso). **Precisa de validação**: os `circuit_id`
  foram escritos de memória e devem ser conferidos contra o retorno real do
  endpoint `/2026/races/` antes do uso na Fase 2.

## Como rodar a coleta

```bash
python -m venv venv
source venv/bin/activate  # no Windows: venv\Scripts\activate
pip install -r requirements.txt

# Coleta os dados da temporada 2026
python -m src.collectors.collect_season --season 2026

# Coleta o histórico dos pilotos por circuito (pode demorar - muitas requisições)
python -m src.collectors.collect_driver_circuit_history --seasons 2019 2020 2021 2022 2023 2024 2025
```

Os dados brutos são salvos em `data/raw/`, organizados por tipo.

## Status da Fase 2

- [x] Validar a tabela `track_types.csv` contra os circuit_ids reais retornados pela API
  — todos os `circuit_id` presentes nos dados batem com o lookup (só `madring`
  ainda não apareceu em nenhum resultado, por ser pista nova em 2026).
- [x] Modelar o schema relacional (PostgreSQL) — `src/etl/schema.sql`
- [x] Construir a pipeline de ETL (raw → banco) — `src/etl/load_to_postgres.py`,
  validada em dry-run contra os dados reais (10 corridas, 195 qualifying,
  362 pitstops, 1755 corridas históricas — 0 erros)
- [x] Containerizar com Docker — `docker-compose.yml`
- [ ] Rodar o ETL contra um Postgres real (bloqueado localmente por falta de
  acesso ao Docker/sudo neste ambiente — pendente de execução)

## Próximos passos (Fase 3)

- Rodar a carga real no Postgres e conferir os dados carregados
- Definir features de treino (histórico do piloto por circuito, tipo de pista, etc.)
- Treinar e avaliar o modelo preditivo
