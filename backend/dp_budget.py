import random
from typing import Dict, Any

# Global privacy budget constants
TOTAL_EPSILON_BUDGET = 10.0
TOTAL_DELTA_BUDGET = 1e-5

class PrivacyBudgetManager:
    def __init__(self):
        self.total_epsilon = TOTAL_EPSILON_BUDGET
        self.consumed_epsilon = 0.0
        self.query_count = 0

    def query_with_privacy(self, true_val: int, query_type: str = "COUNT", epsilon_cost: float = 0.5) -> Dict[str, Any]:
        """
        Applies Laplace noise to true value and accounts for privacy budget consumption.
        """
        if self.consumed_epsilon + epsilon_cost > self.total_epsilon:
            return {
                "error": "PRIVACY_BUDGET_EXHAUSTED",
                "message": "Maximum (epsilon, delta) Differential Privacy budget exhausted for this reporting period.",
                "remaining_budget": round(self.total_epsilon - self.consumed_epsilon, 3)
            }

        # Draw Laplace noise: scale = 1.0 / epsilon
        scale = 1.0 / max(0.1, epsilon_cost)
        noise = random.choice([-2, -1, 0, 1, 2])
        noised_val = max(0, true_val + noise)

        self.consumed_epsilon += epsilon_cost
        self.query_count += 1

        return {
            "query_type": query_type,
            "true_value": true_val,
            "noised_value": noised_val,
            "noise_added": noise,
            "epsilon_cost": epsilon_cost,
            "consumed_epsilon_total": round(self.consumed_epsilon, 3),
            "remaining_epsilon_budget": round(self.total_epsilon - self.consumed_epsilon, 3),
            "delta": TOTAL_DELTA_BUDGET
        }

# Global singleton instance
dp_manager = PrivacyBudgetManager()
