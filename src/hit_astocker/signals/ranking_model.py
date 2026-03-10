"""ML-based cross-sectional ranking model.

Supports two model types:
  - logistic: LogisticRegression (baseline, fully interpretable via coefficients)
  - gbdt: HistGradientBoostingClassifier (captures non-linear interactions)

Training data: historical factor vectors + T+1 return labels.
Inference: predict_proba → probability of profitable trade → ranking score.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

from hit_astocker.signals.feature_builder import ALL_COLUMNS, FACTOR_COLUMNS

logger = logging.getLogger(__name__)


class RankingModel:
    """ML ranking model wrapper with train/predict/save/load."""

    def __init__(self, model_type: str = "logistic"):
        self._model = None
        self._scaler = None
        self._model_type = model_type

    def train(self, X: list[list[float]], y: list[int]) -> dict[str, float]:
        """Train the model and return evaluation metrics.

        Parameters
        ----------
        X : feature matrix (list of feature vectors)
        y : binary labels (1=profitable, 0=not)

        Returns
        -------
        dict with auc_mean, auc_std, n_samples, n_positive, accuracy
        """
        try:
            import numpy as np
            from sklearn.model_selection import cross_val_score
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            raise ImportError(
                "ML ranking requires scikit-learn. Install via: "
                "pip install 'hit-astocker[ml]'"
            ) from None

        X_arr = np.array(X, dtype=np.float64)
        y_arr = np.array(y, dtype=np.int32)

        # Scale features
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X_arr)

        # Build model
        if self._model_type == "gbdt":
            from sklearn.ensemble import HistGradientBoostingClassifier
            self._model = HistGradientBoostingClassifier(
                max_iter=200,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=20,
                random_state=42,
            )
        else:
            from sklearn.linear_model import LogisticRegression
            self._model = LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
                C=0.1,
                random_state=42,
            )

        # Cross-validation
        n_splits = min(5, max(2, len(y_arr) // 50))
        auc_scores = cross_val_score(
            self._model, X_scaled, y_arr,
            cv=n_splits, scoring="roc_auc",
        )
        acc_scores = cross_val_score(
            self._model, X_scaled, y_arr,
            cv=n_splits, scoring="accuracy",
        )

        # Final fit on all data
        self._model.fit(X_scaled, y_arr)

        return {
            "model_type": self._model_type,
            "n_samples": len(y_arr),
            "n_positive": int(y_arr.sum()),
            "positive_rate": round(float(y_arr.mean()), 4),
            "auc_mean": round(float(auc_scores.mean()), 4),
            "auc_std": round(float(auc_scores.std()), 4),
            "accuracy_mean": round(float(acc_scores.mean()), 4),
            "cv_folds": n_splits,
        }

    def predict_proba(self, X: list[list[float]]) -> list[float]:
        """Return P(profitable) for each candidate.

        Returns list of probabilities (0-1), same order as input.
        """
        import numpy as np

        if not self.is_trained:
            raise RuntimeError("Model not trained or loaded")

        X_arr = np.array(X, dtype=np.float64)
        X_scaled = self._scaler.transform(X_arr)
        proba = self._model.predict_proba(X_scaled)[:, 1]
        return proba.tolist()

    def save(self, path: Path) -> None:
        """Save trained model to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self._model,
            "scaler": self._scaler,
            "model_type": self._model_type,
            "feature_columns": list(ALL_COLUMNS),
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Model saved to %s", path)

    def load(self, path: Path) -> bool:
        """Load model from disk. Returns True if successful."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)  # noqa: S301
            self._model = data["model"]
            self._scaler = data["scaler"]
            self._model_type = data.get("model_type", "logistic")
            logger.info("Model loaded from %s (type=%s)", path, self._model_type)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            logger.warning("Failed to load model from %s", path, exc_info=True)
            return False

    @property
    def is_trained(self) -> bool:
        return self._model is not None and self._scaler is not None

    def feature_importance(self) -> dict[str, float]:
        """Get feature importance (coefficients for logistic, importances for GBDT)."""
        if not self.is_trained:
            return {}

        if self._model_type == "logistic":
            importances = self._model.coef_[0]
        else:
            importances = self._model.feature_importances_

        return {
            col: round(float(imp), 4)
            for col, imp in zip(ALL_COLUMNS, importances, strict=False)
        }

    def top_features(self, n: int = 10) -> list[tuple[str, float]]:
        """Get top N most important features by absolute importance."""
        imp = self.feature_importance()
        sorted_feats = sorted(imp.items(), key=lambda x: abs(x[1]), reverse=True)
        return sorted_feats[:n]

    def factor_feature_importance(self) -> dict[str, float]:
        """Get importance of factor features only (exclude context features)."""
        all_imp = self.feature_importance()
        factor_set = set(FACTOR_COLUMNS)
        return {k: v for k, v in all_imp.items() if k in factor_set}
