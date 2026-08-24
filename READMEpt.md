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
| **Duas etapas (hurdle) + RF** | **3,53** | **5,40** | **0,872** |
| Random Forest | 3,75 | 5,57 | 0,871 |
| Duas etapas (hurdle) + linear | 3,77 | 5,44 | 0,868 |
| Ridge | 4,06 | 5,56 | 0,864 |
| Baseline: média da equipe até a rodada | 4,42 | 6,38 | 0,819 |
| Baseline: última corrida da equipe | 4,96 | 7,80 | 0,835 |
| Baseline: média global | 9,73 | 11,22 | — |

### O modelo em duas etapas (hurdle)

39% das linhas valem exatamente 0 pontos, e esses zeros não são "pouca
pontuação" — só os 10 primeiros pontuam, então uma equipe de fundo de grid não
pontuar é um evento diferente de uma equipe forte ter um dia ruim.
`src/models/two_stage.py` separa a pergunta em duas: um classificador para
*esta equipe pontua?* e um regressor treinado **só nas linhas que pontuaram**
para *quantos pontos, dado que pontuou?*. A previsão é
`P(pontuar) × E[pontos | pontuou]`.

Bootstrap pareado (10 mil reamostragens) sobre o ganho de MAE:

| Comparação | Ganho | IC95% | P(melhor) |
|---|---|---|---|
| Duas etapas RF vs RF de etapa única | +0,22 | [+0,03, +0,42] | 0,991 |
| Duas etapas RF vs baseline da média | +0,89 | [+0,01, +1,78] | 0,977 |

Os dois intervalos agora **excluem o zero** — por pouco, no caso do baseline.
O modelo em duas etapas é uma melhora real, ainda que pequena.

### O teste na Mercedes

A Mercedes pontuou em **todas as 12 corridas**, então a etapa de classificação
é trivialmente ~1 para ela e, em princípio, o modelo em duas etapas não
deveria mudar nada. Mesmo assim ajudou (MAE 6,33 contra 7,14 do RF de etapa
única; IC [+0,26, +1,38]). O motivo está na *segunda* etapa, não na primeira:
um regressor único treinado em todas as linhas é puxado para baixo pelos 39%
de zeros, o que subestima sistematicamente as equipes fortes. Treinar a etapa
condicional só com quem pontuou elimina esse puxão.

**O achado mais importante, porém, é negativo.** Entre todas as equipes, a
correlação entre previsto e real é **+0,88**. Dentro da Mercedes sozinha ela é
**-0,16 (p=0,72)** — nenhum sinal. Os pontos reais da Mercedes oscilam de 18 a
40 (desvio 8,2) enquanto o modelo prevê 23-27 toda corrida (desvio 1,3), com
viés quase nulo (+0,22). Ou seja, o modelo **não tem capacidade de prever a
variação corrida a corrida de uma equipe forte**; o que ele faz bem é ordenar
as equipes entre si e acompanhar o nível de uma equipe melhor que uma média
atrasada. Quem ler só o MAE do topo precisa saber que a habilidade está quase
toda em "que equipe é esta", não em "o que vai acontecer no domingo".

Os coeficientes do Ridge fazem sentido físico, o que é um bom sinal de que a
pipeline não está ajustando ruído: a forma na temporada domina (+3,90),
grids melhores (mais baixos) elevam a previsão de pontos (-2,09 em
`grid_best`), e o tipo de pista quase não contribui (|coef| < 0,04) — com 5
categorias em 121 linhas não há dados suficientes para aprender efeito de
pista.

## Previsões

```bash
python -m src.models.predict --modo holdout   # reprevê a última corrida disputada
python -m src.models.predict --modo proxima   # prevê a próxima corrida
```

**Holdout, rodada 12 (GP da Holanda)** — treinado só com as rodadas 2-11,
MAE **3,06**. Acertou em cheio quem não pontuou e a Audi na mosca, mas
subestimou as duas pontuações de 33 (McLaren e Mercedes → ~24) e superestimou
a RB (6,1 contra 0).

**Próxima corrida, rodada 13 (GP da Itália, em Monza)** tem uma ressalva
concreta: o qualifying ainda não aconteceu, então as features de grid não
existem e essa previsão usa um modelo mais fraco, só de forma. Previsto:
Mercedes 23,2, Ferrari 21,9, McLaren 19,4, Red Bull 18,7, e todo o resto
abaixo de 4.

Essa previsão também expõe uma falha real que vale conhecer: **a Cadillac
aparece com 1,2 pontos previstos apesar de nunca ter pontuado na temporada** —
à frente de Williams e Haas, que já pontuaram. Sem o grid, o modelo se apoia
em `hist_circuit_points`, e a Cadillac escala Pérez (média 8,0 em Monza) e
Bottas (7,33), números conquistados em Red Bull e Mercedes/Alfa Romeo, não numa
Cadillac de primeiro ano. Histórico do piloto no circuito não se transfere
quando o carro muda, e o modelo completo só escapa disso porque a posição de
grid denuncia que o carro é lento.

## Próximos passos

- Rodar o backtest de novo conforme as rodadas avançam — a diferença entre
  modelo e baseline é o número a acompanhar
- Ponderar `hist_circuit_points` pela competitividade atual do carro, para que
  um histórico forte feito em carro melhor pare de inflar equipe fraca
- Investigar se *alguma* feature prevê a oscilação corrida a corrida de uma
  única equipe, ou se essa variância é majoritariamente irredutível
  (confiabilidade, clima, safety car)
- Considerar corrigir o problema de paginação descrito acima no coletor

## Autor

Construído como parte de um portfólio de engenharia de dados / data science
por um estudante de Engenharia da Computação.
