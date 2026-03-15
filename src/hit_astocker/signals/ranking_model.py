"""ML-based cross-sectional ranking model.

Supports two model types:
  - logistic: LogisticRegression (baseline, fully interpretable via coefficients)
  - gbdt: GradientBoostingClassifier (captures non-linear interactions)

Training data: historical factor vectors + T+1 return labels.
Inference: predict_proba → probability of profitable trade → ranking score.

Security: model files are verified with HMAC-SHA256 checksum before loading.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import pickle
from pathlib import Path
from typing import Any

from hit_astocker.signals.feature_builder import ALL_COLUMNS, FACTOR_COLUMNS

logger = logging.getLogger(__name__)

# HMAC key for model file integrity verification (not a secret — just tamper detection)
_MODEL_HMAC_KEY = b"hit-astocker-ranking-model-v1"


class RankingModel:
    """ML ranking model wrapper with train/predict/save/load."""

    def __init__(self, model_type: str = "logistic"):
        self._model: Any = None
        self._scaler: Any = None
        self._model_type = model_type
        self._metrics: dict[str, float | int | str] | None = None

    def train(
        self,
        features: list[list[float]],  # noqa: N803
        labels: list[int],
    ) -> dict[str, float | int | str]:
        """Train the model and return evaluation metrics.

        Parameters
        ----------
        features : feature matrix (list of feature vectors)
        labels : binary labels (1=profitable, 0=not)

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
                "ML ranking requires scikit-learn. Install via: pip install 'hit-astocker[ml]'"
            ) from None

        x_arr = np.array(features, dtype=np.float64)
        y_arr = np.array(labels, dtype=np.int32)

        # Build model
        if self._model_type == "gbdt":
            from sklearn.ensemble import GradientBoostingClassifier

            estimator = GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=20,
                subsample=0.8,
                random_state=42,
            )
        else:
            from sklearn.linear_model import LogisticRegression

            estimator = LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
                C=0.1,
                random_state=42,
            )

        # Cross-validation with Pipeline to prevent scaler data leakage.
        # StandardScaler must be fit independently per fold — fitting on all
        # data before CV leaks validation fold statistics into training.
        from sklearn.pipeline import Pipeline

        pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("model", estimator),
            ]
        )
        n_splits = min(5, max(2, len(y_arr) // 50))
        auc_scores = cross_val_score(
            pipeline,
            x_arr,
            y_arr,
            cv=n_splits,
            scoring="roc_auc",
        )
        acc_scores = cross_val_score(
            pipeline,
            x_arr,
            y_arr,
            cv=n_splits,
            scoring="accuracy",
        )

        # Final fit on all data (scaler + model together)
        self._scaler = StandardScaler()
        x_scaled = self._scaler.fit_transform(x_arr)
        self._model = estimator
        self._model.fit(x_scaled, y_arr)

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

    def predict_proba(self, features: list[list[float]]) -> list[float]:
        """Return P(profitable) for each candidate.

        Returns list of probabilities (0-1), same order as input.
        """
        import numpy as np

        if not self.is_trained:
            raise RuntimeError("Model not trained or loaded")

        x_arr = np.array(features, dtype=np.float64)
        x_scaled = self._scaler.transform(x_arr)
        proba = self._model.predict_proba(x_scaled)[:, 1]
        return proba.tolist()

    def save(self, path: Path, metrics: dict[str, float | int | str] | None = None) -> None:
        """Save trained model + HMAC checksum to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self._model,
            "scaler": self._scaler,
            "model_type": self._model_type,
            "feature_columns": list(ALL_COLUMNS),
            "metrics": metrics,
        }
        raw = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)

        # Write model file
        with open(path, "wb") as f:
            f.write(raw)

        # Write HMAC sidecar for integrity verification
        digest = hmac.new(_MODEL_HMAC_KEY, raw, hashlib.sha256).hexdigest()
        path.with_suffix(".sha256").write_text(digest)
        self._metrics = metrics

        # Persist metrics separately so signal generation can gate model usage.
        if metrics is not None:
            path.with_suffix(".meta.json").write_text(
                json.dumps(metrics, ensure_ascii=True, indent=2, sort_keys=True),
            )

        logger.info("Model saved to %s (with .sha256 checksum)", path)

    def load(self, path: Path) -> bool:
        """Load model from disk with HMAC integrity verification.

        Returns True if successful, False if file not found or verification fails.
        """
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return False
        except OSError:
            logger.warning("Failed to read model file %s", path, exc_info=True)
            return False

        # Verify HMAC checksum
        checksum_path = path.with_suffix(".sha256")
        if checksum_path.exists():
            expected = checksum_path.read_text().strip()
            actual = hmac.new(_MODEL_HMAC_KEY, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, actual):
                logger.error(
                    "Model file integrity check FAILED for %s — "
                    "file may be corrupted or tampered with",
                    path,
                )
                return False
        else:
            logger.warning(
                "No checksum file found for %s — skipping integrity check. "
                "Re-run 'train' to generate a verified model.",
                path,
            )

        try:
            data = pickle.loads(raw)  # noqa: S301
            # Verify feature columns match current code
            saved_cols = data.get("feature_columns")
            if saved_cols is not None and saved_cols != list(ALL_COLUMNS):
                logger.error(
                    "Model feature columns mismatch — retrain required. "
                    "saved=%d cols, current=%d cols",
                    len(saved_cols),
                    len(ALL_COLUMNS),
                )
                return False
            self._model = data["model"]
            self._scaler = data["scaler"]
            self._model_type = data.get("model_type", "logistic")
            self._metrics = data.get("metrics")
            if self._metrics is None:
                meta_path = path.with_suffix(".meta.json")
                if meta_path.exists():
                    self._metrics = json.loads(meta_path.read_text())
            logger.info("Model loaded from %s (type=%s)", path, self._model_type)
            return True
        except Exception:
            logger.warning("Failed to deserialize model from %s", path, exc_info=True)
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
            col: round(float(imp), 4) for col, imp in zip(ALL_COLUMNS, importances, strict=False)
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

    @property
    def metrics(self) -> dict[str, float | int | str] | None:
        return self._metrics

    def is_usable(self, min_auc: float = 0.55) -> bool:
        """Return whether the loaded model passed the minimum validation bar."""
        if not self.is_trained or self._metrics is None:
            return False
        auc = self._metrics.get("auc_mean")
        try:
            return float(auc) >= min_auc
        except (TypeError, ValueError):
            return False
