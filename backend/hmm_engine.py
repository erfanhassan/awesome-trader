import numpy as np
from hmmlearn import hmm
import joblib
import os
import threading
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

class HMMEngine:
    def __init__(self, model_path="hmm_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.is_training = False
        
        # 3 Regimes: Chop, Trend, Liquidation Cascade
        self.n_components = 3
        self.regime_map = {0: "Chop", 1: "Trend", 2: "Liquidation Cascade"}
        
        self.load_model()

    def load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                print("Loaded existing HMM model.")
            except Exception as e:
                print(f"Failed to load HMM model: {e}")
                self.model = None

    def save_model(self):
        if self.model:
            joblib.dump(self.model, self.model_path)
            print("Saved HMM model.")

    def _train_async(self, X):
        try:
            print(f"Starting HMM async training on {len(X)} samples...")
            new_model = hmm.GaussianHMM(n_components=self.n_components, covariance_type="full", n_iter=100, random_state=42)
            new_model.fit(X)
            
            # Re-map regimes based on variance/means to ensure consistency
            # High variance usually means Cascade, low variance means Chop.
            variances = np.array([np.trace(cov) for cov in new_model.covars_])
            sorted_idx = np.argsort(variances)
            
            # sorted_idx[0] = lowest variance -> Chop
            # sorted_idx[1] = medium variance -> Trend
            # sorted_idx[2] = highest variance -> Liquidation Cascade
            
            self.regime_map = {
                sorted_idx[0]: "Chop",
                sorted_idx[1]: "Trend",
                sorted_idx[2]: "Liquidation Cascade"
            }
            
            self.model = new_model
            self.save_model()
            print("HMM training complete.")
        except Exception as e:
            print(f"HMM Training failed: {e}")
        finally:
            self.is_training = False

    def retrain(self, features_history):
        """
        features_history: list of [vol_velocity, liq_proximity, volatility_std]
        """
        if len(features_history) < 100:
            print("Not enough data to train HMM.")
            return

        if not self.is_training:
            self.is_training = True
            X = np.array(features_history)
            
            # Run in a background thread to prevent blocking
            thread = threading.Thread(target=self._train_async, args=(X,))
            thread.start()

    def predict_regime(self, current_features):
        """
        current_features: [vol_velocity, liq_proximity, volatility_std]
        Returns: (regime_name, confidence)
        """
        if self.model is None:
            # Fallback if no model trained yet
            return "Chop", 0.5
            
        try:
            X = np.array([current_features])
            logprob, state = self.model.decode(X, algorithm="viterbi")
            probs = self.model.predict_proba(X)
            state_idx = state[0]
            confidence = probs[0][state_idx]
            
            regime_name = self.regime_map.get(state_idx, "Chop")
            return regime_name, confidence
        except Exception as e:
            print(f"HMM Prediction error: {e}")
            return "Chop", 0.5
