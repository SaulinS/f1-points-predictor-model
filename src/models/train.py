"""
Treino e avaliação do modelo de pontos por equipe/corrida.

Validação: backtest de janela expansiva. Para cada rodada de teste, o modelo é
treinado apenas com as rodadas anteriores e prevê aquela rodada. Um k-fold
aleatório seria inadequado aqui -- ele treinaria com corridas futuras para
prever corridas passadas, produzindo um número bonito que não se sustenta em
uso real, que é sempre "prever a próxima corrida".

Comparação com baselines é a parte mais importante deste script. Com uma base
pequena e equipes de força muito separada (Mercedes ~30 pts/corrida, Cadillac
0), prever simplesmente "a média da equipe até agora" já acerta bastante. Um
modelo só justifica sua complexidade se bater esse chute.

Uso:
    python -m src.models.train
"""

import logging

import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from scipy.stats import spearmanr

from src.models.two_stage import HurdleRegressor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

NUMERIC_FEATURES = [
    "grid_best",
    "grid_mean",
    "hist_circuit_points",
    "form_last3",
    "form_todate",
    "dnf_rate_todate",
]
CATEGORICAL_FEATURES = ["track_type"]
TARGET = "team_points"

# Rodada a partir da qual avaliamos. Antes disso há poucas corridas no passado
# para treinar qualquer coisa -- começar em 6 dá ~44 linhas de treino no
# primeiro fold, que já é pouco, mas não absurdo.
FIRST_TEST_ROUND = 6


def make_model(kind: str, numeric_features: list[str] | None = None) -> Pipeline:
    """
    Monta o pipeline completo (imputação -> escala -> modelo).

    A imputação fica dentro do pipeline de propósito: assim a mediana é
    calculada só com os dados de treino de cada fold, e não com a base
    inteira, que seria outra forma sutil de vazamento.

    `numeric_features` permite treinar um modelo com um subconjunto das
    colunas -- usado para prever corridas cujo qualifying ainda não aconteceu,
    onde as features de grid não existem.
    """
    numeric_features = numeric_features or NUMERIC_FEATURES
    numeric = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    pre = ColumnTransformer([
        ("num", numeric, numeric_features),
        ("cat", categorical, CATEGORICAL_FEATURES),
    ])

    if kind == "ridge":
        # Regularização forte é proposital: com ~50-100 linhas de treino e 10
        # colunas depois do one-hot, um modelo pouco penalizado decora o treino.
        model = Ridge(alpha=10.0)
    elif kind == "rf":
        model = RandomForestRegressor(
            n_estimators=300,
            max_depth=4,          # árvores rasas pelo mesmo motivo
            min_samples_leaf=5,
            random_state=42,
        )
    elif kind == "hurdle":
        # Duas etapas com modelos lineares: a etapa condicional treina só com
        # as linhas que pontuaram (~60% da base), então precisa ser simples.
        model = HurdleRegressor(
            classifier=LogisticRegression(C=1.0, max_iter=1000),
            regressor=Ridge(alpha=10.0),
        )
    elif kind == "hurdle_rf":
        model = HurdleRegressor(
            classifier=RandomForestClassifier(
                n_estimators=300, max_depth=4, min_samples_leaf=5, random_state=42
            ),
            regressor=RandomForestRegressor(
                n_estimators=300, max_depth=4, min_samples_leaf=5, random_state=42
            ),
        )
    else:
        raise ValueError(f"modelo desconhecido: {kind}")

    return Pipeline([("pre", pre), ("model", model)])


def within_race_spearman(df: pd.DataFrame, pred_col: str) -> float:
    """
    Correlação de ordenação dentro de cada corrida, medindo se o modelo acerta
    quem pontua mais que quem naquele fim de semana.

    É a métrica mais próxima do uso prático: errar a escala dos pontos importa
    menos do que trocar a ordem das equipes.
    """
    rhos = []
    for _, g in df.groupby("round"):
        # Baselines de valor único (ex: média global) não têm ordenação para
        # comparar -- a correlação seria indefinida, então ficam de fora.
        if g[TARGET].nunique() < 2 or g[pred_col].nunique() < 2:
            continue
        rho = spearmanr(g[TARGET], g[pred_col]).statistic
        if not np.isnan(rho):
            rhos.append(rho)
    return float(np.mean(rhos)) if rhos else float("nan")


def backtest(df: pd.DataFrame) -> pd.DataFrame:
    """
    Backtest de janela expansiva: treina em tudo que veio antes da rodada de
    teste e prevê apenas aquela rodada.
    """
    test_rounds = sorted(r for r in df["round"].unique() if r >= FIRST_TEST_ROUND)
    rows = []

    for test_round in test_rounds:
        train = df[df["round"] < test_round]
        test = df[df["round"] == test_round].copy()

        for kind in ("ridge", "rf", "hurdle", "hurdle_rf"):
            model = make_model(kind)
            model.fit(train[NUMERIC_FEATURES + CATEGORICAL_FEATURES], train[TARGET])
            test[f"pred_{kind}"] = model.predict(test[NUMERIC_FEATURES + CATEGORICAL_FEATURES])

        # Baselines, calculados sem nenhum aprendizado:
        # - media_equipe: a própria feature de média até a rodada anterior
        # - ultima_corrida: repete o resultado mais recente da equipe
        # - media_global: a média de pontos de todas as equipes no treino
        test["pred_media_equipe"] = test["form_todate"]
        test["pred_ultima_corrida"] = test["constructor_id"].map(
            train.sort_values("round").groupby("constructor_id")[TARGET].last()
        )
        test["pred_media_global"] = train[TARGET].mean()

        test["test_round"] = test_round
        rows.append(test)

    return pd.concat(rows, ignore_index=True)


def evaluate(results: pd.DataFrame) -> pd.DataFrame:
    pred_cols = [c for c in results.columns if c.startswith("pred_")]
    report = []
    for col in pred_cols:
        valid = results[results[col].notna()]
        report.append({
            "modelo": col.replace("pred_", ""),
            "MAE": mean_absolute_error(valid[TARGET], valid[col]),
            "RMSE": float(np.sqrt(mean_squared_error(valid[TARGET], valid[col]))),
            "spearman_intra_corrida": within_race_spearman(valid, col),
            "n": len(valid),
        })
    return pd.DataFrame(report).sort_values("MAE").reset_index(drop=True)


def mae_by_team(results: pd.DataFrame) -> pd.DataFrame:
    """
    Erro por equipe. É aqui que se vê para quem o modelo em duas etapas serve:
    o ganho dele deve aparecer nas equipes que zeram com frequência, não nas
    que pontuam toda corrida.
    """
    pred_cols = [c for c in results.columns if c.startswith("pred_")]
    rows = []
    for team, g in results.groupby("constructor_id"):
        row = {"equipe": team, "pts_medio": g[TARGET].mean(), "zeros": int((g[TARGET] == 0).sum()), "n": len(g)}
        for col in pred_cols:
            valid = g[g[col].notna()]
            row[col.replace("pred_", "")] = mean_absolute_error(valid[TARGET], valid[col])
        rows.append(row)
    return (
        pd.DataFrame(rows)
        .sort_values("pts_medio", ascending=False)
        .set_index("equipe")
        .round(2)
    )


def inspect_ridge_coefficients(df: pd.DataFrame):
    """Treina uma vez na base toda só para ler os coeficientes (interpretação)."""
    model = make_model("ridge")
    model.fit(df[NUMERIC_FEATURES + CATEGORICAL_FEATURES], df[TARGET])
    names = model.named_steps["pre"].get_feature_names_out()
    coefs = model.named_steps["model"].coef_
    return (
        pd.DataFrame({"feature": names, "coef": coefs})
        .assign(abs_coef=lambda d: d["coef"].abs())
        .sort_values("abs_coef", ascending=False)
        .drop(columns="abs_coef")
        .reset_index(drop=True)
    )


def main():
    path = PROCESSED_DIR / "team_race_features.csv"
    df = pd.read_csv(path)
    logger.info(f"Base: {len(df)} linhas, rodadas {df['round'].min()}-{df['round'].max()}")

    results = backtest(df)
    logger.info(
        f"Backtest: {results['test_round'].nunique()} rodadas de teste "
        f"({results['test_round'].min()}-{results['test_round'].max()}), "
        f"{len(results)} previsões por modelo"
    )

    report = evaluate(results)
    print("\n=== Desempenho no backtest (janela expansiva) ===")
    print(report.to_string(index=False))

    print("\n=== MAE por equipe (ordenado por pontuação média) ===")
    print(mae_by_team(results).to_string())

    print("\n=== Coeficientes do Ridge (base completa) ===")
    print(inspect_ridge_coefficients(df).to_string(index=False))

    out = PROCESSED_DIR / "backtest_predictions.csv"
    keep = ["round", "constructor_id", TARGET] + [c for c in results.columns if c.startswith("pred_")]
    results[keep].to_csv(out, index=False)
    logger.info(f"Previsões salvas em: {out}")


if __name__ == "__main__":
    main()
