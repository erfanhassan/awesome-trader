class RiskEngine:
    def __init__(self):
        pass

    def calculate_historical_stats(self, signal_history, strategy_name, direction):
        # Filter history for the specific strategy and direction
        relevant_trades = [
            t for t in signal_history 
            if t.get("strategy") == strategy_name and t.get("direction") == direction and t.get("status") in ["PROFIT", "LOSS", "LIQUIDATED"]
        ]
        
        if not relevant_trades:
            # Fallback prior if no data exists
            return {"win_rate": 0.5, "avg_win": 1.5, "avg_loss": 1.0}
            
        wins = [t for t in relevant_trades if t.get("net_profit", 0) > 0]
        losses = [t for t in relevant_trades if t.get("net_profit", 0) <= 0]
        
        win_rate = len(wins) / len(relevant_trades)
        
        # We look at raw percentages rather than absolute USD since size varies
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 1.5
        avg_loss = abs(sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 1.0
        
        # Avoid division by zero
        if avg_loss == 0: avg_loss = 1.0
        
        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss
        }

    def calculate_ev(self, win_rate, avg_win, avg_loss):
        """
        Expected Value (EV) = (P_win * Average Win) - (P_loss * Average Loss)
        Returns the EV. If <= 0, the trade is mathematically invalid.
        """
        p_loss = 1.0 - win_rate
        ev = (win_rate * avg_win) - (p_loss * avg_loss)
        return ev

    def calculate_kelly_fraction(self, win_rate, avg_win, avg_loss, hmm_confidence):
        """
        f* = (bp - (1-p)) / b
        b = average win / average loss (the payoff ratio)
        p = probability of win
        Returns the optimal fraction of bankroll to risk.
        We scale this down by the HMM confidence (Half-Kelly or Quarter-Kelly).
        """
        b = avg_win / avg_loss
        if b == 0: return 0
        
        kelly = (b * win_rate - (1 - win_rate)) / b
        
        if kelly <= 0: return 0
        
        # Apply Half-Kelly scaled by confidence
        safe_kelly = (kelly * 0.5) * hmm_confidence
        return max(0, min(safe_kelly, 1.0)) # Cap at 1.0 (100% of balance)

    def calculate_live_bayesian_update(self, prior_win_rate, current_delta, avg_delta, direction="LONG"):
        """
        Naive Bayesian update for live trade execution.
        We treat a favorable volume delta as positive evidence, and adverse delta as negative.
        Adjusts the prior win rate probability in real-time.
        """
        # Assume max evidence effect is +/- 20% shift in probability based on extreme delta
        if avg_delta == 0: avg_delta = 1.0
        
        # Invert delta if we are SHORT (since negative delta is good for shorts)
        if direction == "SHORT":
            effective_delta = -current_delta
        else:
            effective_delta = current_delta
            
        delta_ratio = effective_delta / abs(avg_delta)
        
        # Logistic curve mapping delta_ratio to a probability modifier [0, 1]
        import math
        # clamp ratio
        delta_ratio = max(-3.0, min(3.0, delta_ratio)) 
        evidence_multiplier = 1 / (1 + math.exp(-delta_ratio)) # sigmoid
        
        # Update probability: mix prior with the new evidence (Stickiness: 80% Prior / 20% Evidence)
        posterior_prob = (prior_win_rate * 0.8) + (evidence_multiplier * 0.2)
        return posterior_prob
