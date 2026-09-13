import os
import joblib
import numpy as np
import logging
from sklearn.linear_model import SGDClassifier
from typing import List, Tuple

logger = logging.getLogger(__name__)

class ProbabilityModel:
    def __init__(self, model_path="prob_model.pkl"):
        self.model_path = model_path
        self.is_trained = False
        
        # We use SGDClassifier for online learning (partial_fit)
        # Classes: 0: DOWN, 1: FLAT, 2: UP
        self.model = SGDClassifier(loss='log_loss', penalty='l2', max_iter=1000, tol=1e-3)
        self.classes = np.array([0, 1, 2])
        
        # Experience replay buffer for batch training
        self.experience_X = []
        self.experience_y = []
        
        self.load_model()

    def _get_label(self, c_open: float, c_close: float) -> int:
        if c_open == 0:
            return 1
        pct_change = (c_close - c_open) / c_open
        
        # Consider a move of less than 0.01% as flat
        if pct_change > 0.0001:
            return 2 # UP
        elif pct_change < -0.0001:
            return 0 # DOWN
        else:
            return 1 # FLAT

    def extract_features(self, history: List[dict], trade_data: dict) -> np.ndarray:
        """
        Extracts features from the recent history and trade_data for the given symbol.
        Expects history to be 1m klines.
        Returns a numpy array of features.
        """
        if not history or len(history) < 3:
            return np.zeros(6)
            
        current = history[-1]
        
        # Price and volume features
        c_open = current["o"]
        c_close = current["c"]
        c_high = current["h"]
        c_low = current["l"]
        c_vol = current["v"]
        
        # Calculate recent delta and previous delta
        # If trade_data is provided, use real delta. Here we might fall back to approximated if unavailable.
        delta = trade_data.get("delta", 0.0)
        
        delta_history = trade_data.get("delta_history", [])
        prev_delta_1 = delta_history[-1] if len(delta_history) > 0 else 0.0
        prev_delta_2 = delta_history[-2] if len(delta_history) > 1 else 0.0
        
        # Calculate dollar-volume ratio vs average
        prev_10 = history[-11:-1]
        avg_vol = sum(c["v"] * c["c"] for c in prev_10) / len(prev_10) if prev_10 else 1.0
        c_dollar_vol = c_vol * c_close
        vol_ratio = c_dollar_vol / avg_vol if avg_vol > 0 else 1.0
        
        # Price momentum (return of previous candle)
        prev_c = history[-2]
        momentum = (prev_c["c"] - prev_c["o"]) / prev_c["o"] if prev_c["o"] > 0 else 0.0
        
        # We can also add session feature, but let's keep it simple first
        # 6 features: delta, prev_delta_1, prev_delta_2, vol_ratio, momentum, close_pct_change
        features = np.array([delta, prev_delta_1, prev_delta_2, vol_ratio, momentum, (c_close - c_open)/c_open if c_open > 0 else 0.0])
        return features

    def predict_direction(self, features: np.ndarray) -> Tuple[float, float, float]:
        """
        Returns probabilities (p_down, p_flat, p_up)
        """
        if not self.is_trained:
            # Return uniform if not trained
            return 0.33, 0.33, 0.33
            
        try:
            # model.predict_proba expects a 2D array
            probs = self.model.predict_proba([features])[0]
            # probs should map to classes 0 (DOWN), 1 (FLAT), 2 (UP)
            
            p_down = 0.0
            p_flat = 0.0
            p_up = 0.0
            
            for cls_idx, cls_val in enumerate(self.model.classes_):
                if cls_val == 0: p_down = probs[cls_idx]
                elif cls_val == 1: p_flat = probs[cls_idx]
                elif cls_val == 2: p_up = probs[cls_idx]
                
            return p_down, p_flat, p_up
            
        except Exception as e:
            logger.error(f"Error predicting direction: {e}")
            return 0.33, 0.33, 0.33

    def online_learn(self, features: np.ndarray, c_open: float, c_close: float):
        """
        Updates the model with a single new sample.
        Called when a 1m candle closes.
        """
        label = self._get_label(c_open, c_close)
        
        self.experience_X.append(features)
        self.experience_y.append(label)
        
        # Batch train every 50 candles to maintain stability
        if len(self.experience_X) >= 50:
            X = np.array(self.experience_X)
            y = np.array(self.experience_y)
            
            self.model.partial_fit(X, y, classes=self.classes)
            self.is_trained = True
            
            # Keep recent history in replay buffer, clear oldest
            self.experience_X = self.experience_X[-10:]
            self.experience_y = self.experience_y[-10:]
            
            # Periodically save
            self.save_model()

    def save_model(self):
        try:
            joblib.dump(self.model, self.model_path)
        except Exception as e:
            logger.error(f"Error saving probability model: {e}")

    def load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                # Check if it was ever trained (has coef_)
                if hasattr(self.model, 'coef_'):
                    self.is_trained = True
                    logger.info("Loaded pre-trained Probability Model.")
            except Exception as e:
                logger.error(f"Error loading probability model: {e}")
                # Reset model if load fails
                self.model = SGDClassifier(loss='log_loss', penalty='l2', max_iter=1000, tol=1e-3)
                self.is_trained = False
