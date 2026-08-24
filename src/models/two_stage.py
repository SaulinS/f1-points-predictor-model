"""
Modelo em duas etapas (hurdle) para pontos por equipe/corrida.

Motivação: 39% das linhas da base valem exatamente 0 pontos, e esses zeros não
são "pouca pontuação" -- são um evento diferente. Na F1 só os 10 primeiros
pontuam, então uma equipe de fundo de grid não pontua *nada* na maioria das
corridas, e quando pontua costuma ser um resultado atípico. Um regressor único
tenta explicar essas duas situações com a mesma equação e acaba prevendo
valores intermediários que nunca acontecem.

O modelo separa a decisão em duas perguntas:
    1. Esta equipe pontua nesta corrida?          -> classificador
    2. Se pontuar, quantos pontos?                -> regressor (só nas linhas > 0)

A previsão final é o valor esperado: P(pontuar) * E[pontos | pontuou].
"""

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, clone


class HurdleRegressor(BaseEstimator, RegressorMixin):
    """
    Combina um classificador (pontua ou não) com um regressor condicional
    (quantos pontos, dado que pontuou).

    Opera sobre a matriz já pré-processada, então é usado como último passo de
    um Pipeline, igual a qualquer outro estimador do scikit-learn.
    """

    def __init__(self, classifier=None, regressor=None):
        self.classifier = classifier
        self.regressor = regressor

    def fit(self, X, y):
        y = np.asarray(y, dtype=float)
        scored = y > 0

        self.classifier_ = clone(self.classifier)
        self.regressor_ = clone(self.regressor)

        # Nos primeiros folds do backtest o treino pode não conter os dois
        # casos (ex: nenhuma equipe zerou ainda). Sem duas classes não há o que
        # classificar, então guardamos a constante e pulamos a etapa 1.
        self.classes_seen_ = np.unique(scored)
        if len(self.classes_seen_) < 2:
            self.constant_proba_ = float(scored[0])
        else:
            self.constant_proba_ = None
            self.classifier_.fit(X, scored)

        # A etapa 2 aprende só com quem pontuou -- é isso que a mantém livre da
        # massa de zeros que distorce um regressor único.
        if scored.sum() >= 2:
            self.regressor_.fit(X[scored], y[scored])
            self.fallback_mean_ = None
        else:
            # Dados insuficientes para ajustar a etapa condicional.
            self.fallback_mean_ = float(y[scored].mean()) if scored.any() else 0.0

        return self

    def predict(self, X):
        if self.constant_proba_ is not None:
            proba = np.full(X.shape[0], self.constant_proba_)
        else:
            proba = self.classifier_.predict_proba(X)[:, 1]

        if self.fallback_mean_ is not None:
            conditional = np.full(X.shape[0], self.fallback_mean_)
        else:
            conditional = self.regressor_.predict(X)

        # Pontos não são negativos; o regressor condicional pode extrapolar
        # abaixo de zero em linhas extremas.
        return proba * np.clip(conditional, 0, None)

    def predict_parts(self, X):
        """Devolve as duas etapas separadas, para inspeção."""
        if self.constant_proba_ is not None:
            proba = np.full(X.shape[0], self.constant_proba_)
        else:
            proba = self.classifier_.predict_proba(X)[:, 1]
        conditional = (
            np.full(X.shape[0], self.fallback_mean_)
            if self.fallback_mean_ is not None
            else np.clip(self.regressor_.predict(X), 0, None)
        )
        return proba, conditional
