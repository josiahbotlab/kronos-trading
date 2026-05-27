"""
ML Regime Filter — Random Forest Classifier
===============================================
Wraps sklearn RandomForestClassifier to filter trade signals.

Usage:
    rf = RegimeFilter()
    rf.train(X, y)         # X: (n_samples, 14), y: (n_samples,) binary
    rf.save("model.pkl")
    rf.load("model.pkl")
    prob = rf.predict_proba(features)  # probability of winning trade
"""

from pathlib import Path
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneOut, cross_val_predict


MODEL_DIR = Path(__file__).parent / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "regime_filter.pkl"


class RegimeFilter:
    """Random Forest trade filter."""

    def __init__(self, model_path: Path | str | None = None):
        self.model: RandomForestClassifier | None = None
        self._model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH

        # Try to load existing model
        if self._model_path.exists():
            self.load(self._model_path)

    def train(self, X: np.ndarray, y: np.ndarray) -> dict:
        """
        Train the Random Forest on trade features + win/loss labels.

        Uses conservative hyperparameters for small sample sizes:
          - max_depth=3 to prevent overfitting
          - min_samples_leaf=2 (given ~20-40 samples)
          - n_estimators=100

        Args:
            X: Feature matrix (n_samples, n_features).
            y: Binary labels (1=win, 0=loss).

        Returns:
            Dict with training metrics (LOO accuracy, feature importances).
        """
        n_samples = len(y)
        n_wins = int(np.sum(y))
        n_losses = n_samples - n_wins

        # Hyperparameters tuned for small samples
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=3,
            min_samples_leaf=2,
            min_samples_split=3,
            max_features='sqrt',
            class_weight='balanced',  # handle win/loss imbalance
            random_state=42,
            n_jobs=-1,
        )

        # Leave-One-Out cross-validation for small samples
        loo = LeaveOneOut()
        loo_preds = cross_val_predict(self.model, X, y, cv=loo, method='predict')
        loo_accuracy = np.mean(loo_preds == y)

        # Also get LOO probabilities for calibration insight
        loo_probs = cross_val_predict(self.model, X, y, cv=loo, method='predict_proba')
        # loo_probs shape: (n_samples, 2) — column 1 is P(win)
        avg_win_prob_for_wins = np.mean(loo_probs[y == 1, 1]) if n_wins > 0 else 0.0
        avg_win_prob_for_losses = np.mean(loo_probs[y == 0, 1]) if n_losses > 0 else 0.0

        # Train final model on all data
        self.model.fit(X, y)

        # Feature importances
        from strategies.augxmented.ml.features import FEATURE_NAMES
        importances = dict(zip(FEATURE_NAMES, self.model.feature_importances_))

        metrics = {
            'n_samples': n_samples,
            'n_wins': n_wins,
            'n_losses': n_losses,
            'loo_accuracy': loo_accuracy,
            'avg_win_prob_for_wins': avg_win_prob_for_wins,
            'avg_win_prob_for_losses': avg_win_prob_for_losses,
            'feature_importances': importances,
        }

        return metrics

    def predict_proba(self, features: np.ndarray) -> float:
        """
        Predict probability that a trade will be a winner.

        Args:
            features: Feature vector (n_features,) or (1, n_features).

        Returns:
            Probability of win (0.0 to 1.0).
        """
        if self.model is None:
            return 1.0  # no model loaded, pass all trades through

        if features.ndim == 1:
            features = features.reshape(1, -1)

        proba = self.model.predict_proba(features)
        # Column 1 = P(class=1) = P(win)
        return float(proba[0, 1])

    def save(self, path: Path | str | None = None):
        """Save trained model to disk."""
        path = Path(path) if path else self._model_path
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, path)

    def load(self, path: Path | str | None = None):
        """Load model from disk."""
        path = Path(path) if path else self._model_path
        if path.exists():
            self.model = joblib.load(path)
        else:
            self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None
