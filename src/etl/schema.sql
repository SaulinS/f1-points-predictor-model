-- Schema do banco de dados para o F1 Team Points Predictor
-- Convenção: todas as chaves de negócio da API (circuitId, driverId, constructorId)
-- são mantidas como texto (não convertidas para int), porque são o identificador
-- natural usado pela Jolpica-F1 -- isso evita uma camada extra de mapeamento
-- id-texto <-> id-numerico durante o ETL.

CREATE TABLE circuits (
    circuit_id      VARCHAR(50) PRIMARY KEY,
    circuit_name    VARCHAR(150) NOT NULL,
    track_type      VARCHAR(30),   -- rua, alta_velocidade, tecnica, mista, rua_alta_velocidade
    country         VARCHAR(80),
    locality        VARCHAR(80),
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6)
);

CREATE TABLE drivers (
    driver_id       VARCHAR(50) PRIMARY KEY,
    driver_code     VARCHAR(5),
    given_name      VARCHAR(80) NOT NULL,
    family_name     VARCHAR(80) NOT NULL,
    nationality     VARCHAR(60)
);

CREATE TABLE constructors (
    constructor_id  VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    nationality     VARCHAR(60)
);

CREATE TABLE races (
    race_id         SERIAL PRIMARY KEY,
    season          SMALLINT NOT NULL,
    round           SMALLINT NOT NULL,
    circuit_id      VARCHAR(50) NOT NULL REFERENCES circuits(circuit_id),
    race_name       VARCHAR(150),
    race_date       DATE,
    UNIQUE (season, round)
);

CREATE TABLE results (
    result_id       SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES races(race_id),
    driver_id       VARCHAR(50) NOT NULL REFERENCES drivers(driver_id),
    constructor_id  VARCHAR(50) NOT NULL REFERENCES constructors(constructor_id),
    grid            SMALLINT,       -- posição de largada
    position        SMALLINT,       -- posição final (NULL se não terminou)
    points           NUMERIC(5,2) NOT NULL DEFAULT 0,
    status          VARCHAR(60),    -- 'Finished', 'Retired', 'Accident', etc.
    laps            SMALLINT,
    UNIQUE (race_id, driver_id)
);

CREATE TABLE qualifying (
    qualifying_id   SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES races(race_id),
    driver_id       VARCHAR(50) NOT NULL REFERENCES drivers(driver_id),
    constructor_id  VARCHAR(50) NOT NULL REFERENCES constructors(constructor_id),
    position        SMALLINT,
    q1_time         VARCHAR(20),
    q2_time         VARCHAR(20),
    q3_time         VARCHAR(20),
    UNIQUE (race_id, driver_id)
);

CREATE TABLE pitstops (
    pitstop_id      SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES races(race_id),
    driver_id       VARCHAR(50) NOT NULL REFERENCES drivers(driver_id),
    stop_number     SMALLINT NOT NULL,
    lap             SMALLINT,
    stop_time       VARCHAR(20),    -- horário do dia em que ocorreu
    duration_ms     INTEGER,        -- duração em milissegundos, para calculos
    UNIQUE (race_id, driver_id, stop_number)
);

-- Índices para acelerar as queries mais comuns da fase de modelagem:
-- "histórico do piloto neste circuito" e "resultados da temporada 2026"
CREATE INDEX idx_races_season ON races(season);
CREATE INDEX idx_races_circuit ON races(circuit_id);
CREATE INDEX idx_results_driver ON results(driver_id);
CREATE INDEX idx_results_constructor ON results(constructor_id);
CREATE INDEX idx_results_race ON results(race_id);

-- View: pontos da equipe por corrida -- é o ALVO do modelo preditivo.
-- Soma os pontos dos dois pilotos de cada equipe em cada corrida de 2026.
CREATE VIEW team_race_points AS
SELECT
    r.race_id,
    ra.season,
    ra.round,
    ra.circuit_id,
    r.constructor_id,
    SUM(r.points) AS team_points,
    COUNT(*) FILTER (WHERE r.status != 'Finished' AND r.status NOT LIKE '%Lap%') AS dnf_count
FROM results r
JOIN races ra ON ra.race_id = r.race_id
GROUP BY r.race_id, ra.season, ra.round, ra.circuit_id, r.constructor_id;

-- View: histórico do piloto por circuito (temporadas anteriores a 2026) --
-- é a FEATURE de "desempenho do piloto naquela pista".
CREATE VIEW driver_circuit_history AS
SELECT
    r.driver_id,
    ra.circuit_id,
    ra.season,
    r.position,
    r.points,
    r.status
FROM results r
JOIN races ra ON ra.race_id = r.race_id
WHERE ra.season < 2026;

-- View: equipes que efetivamente competiram na temporada 2026.
-- A tabela `constructors` acumula toda equipe já vista (inclusive em anos
-- anteriores, com nomes que não existem mais -- ex: Racing Point, Alfa Romeo).
-- Use esta view sempre que precisar da lista "oficial" de equipes atuais,
-- em vez de consultar `constructors` diretamente.
CREATE VIEW constructors_2026 AS
SELECT DISTINCT c.constructor_id, c.name, c.nationality
FROM constructors c
JOIN results r ON r.constructor_id = c.constructor_id
JOIN races ra ON ra.race_id = r.race_id
WHERE ra.season = 2026;
