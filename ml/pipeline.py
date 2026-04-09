import logging
import numpy as np
import pandas as pd
import lightgbm as lgb
import optuna
import shap
from typing import Tuple, Iterator
from sklearn.model_selection import BaseCrossValidator
from scipy.stats import spearmanr
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

class PurgedKFold(BaseCrossValidator):
    def __init__(self, n_splits=5, embargo_pct=0.05): self.n_splits, self.embargo_pct = n_splits, embargo_pct
    def split(self, X, y=None, groups=None) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        n, split_size, embargo_len = len(X), len(X)//self.n_splits, int((len(X)//self.n_splits)*self.embargo_pct)
        idx = np.arange(n)
        for i in range(self.n_splits):
            v_s, v_e = i*split_size, i*split_size+split_size
            yield np.concatenate([idx[:max(0, v_s-embargo_len)], idx[v_e:]]), idx[v_s:v_e]
    def get_n_splits(self, X=None, y=None, groups=None) -> int: return self.n_splits

def compute_ic_ir(y_true, y_pred):
    rho, _ = spearmanr(y_true, y_pred)
    return float(rho), float(rho)/np.std([rho]) if np.std([rho])>1e-6 else 0.0

@dataclass
class MLPipeline:
    target_horizon: int = 5; n_trials: int = 50
    cv: BaseCrossValidator = field(default_factory=lambda: PurgedKFold(5, 0.1))
    def _objective(self, trial, X, y):
        params = {"objective":"regression","metric":"rmse","boosting_type":"gbdt",
                  "num_leaves":trial.suggest_int("num_leaves",20,200),"learning_rate":trial.suggest_float("lr",0.01,0.2,log=True),
                  "feature_fraction":trial.suggest_float("ff",0.5,0.9),"verbosity":-1}
        scores = []
        for tr_i, va_i in self.cv.split(X, y):
            m = lgb.train(params, lgb.Dataset(X.iloc[tr_i], label=y.iloc[tr_i]),
                          valid_sets=[lgb.Dataset(X.iloc[va_i], label=y.iloc[va_i])],
                          callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
            scores.append(compute_ic_ir(y.iloc[va_i].values, m.predict(X.iloc[va_i]))[0])
        return np.mean(scores)
    def run(self, features, returns):
        y = returns.pct_change(self.target_horizon).shift(-self.target_horizon)
        mask = ~y.isna() & features.notna().all(axis=1)
        X, y = features.loc[mask], y.loc[mask]
        logger.info(f"📊 训练样本: {len(X)} | 特征: {X.shape[1]}")
        study = optuna.create_study(direction="maximize")
        study.optimize(lambda t: self._objective(t, X, y), n_trials=self.n_trials, show_progress_bar=True)
        model = lgb.train({**study.best_params, "objective":"regression","metric":"rmse"}, lgb.Dataset(X, label=y))
        shap_vals = shap.TreeExplainer(model).shap_values(X)
        return {"model":model, "params":study.best_params, "ic":compute_ic_ir(y.values, model.predict(X))[0],
                "shap":pd.DataFrame({"feat":X.columns, "imp":np.abs(shap_vals).mean(0)}).sort_values("imp", ascending=False)}
