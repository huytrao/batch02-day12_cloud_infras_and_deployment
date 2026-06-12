"""
Cost Guard — Monthly per-user and global budget protection.

Tracks cumulative LLM API spend in Redis.
Rejects requests (HTTP 402) when user or global budget is exceeded.
Budget resets monthly (key expires after 32 days).

Exercise 4.4 solution from CODE_LAB.md.
"""
import time
import logging
from fastapi import HTTPException
import redis as redis_module

from app.config import settings

logger = logging.getLogger(__name__)

# Pricing per 1K tokens (GPT-4o-mini approximate)
PRICE_PER_1K_INPUT_TOKENS = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006

# ─── Redis connection ───────────────────────────────────────────────────────
try:
    _redis = redis_module.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store: dict = {}


class CostGuard:
    """
    Monthly budget guard per user and globally.

    Logic (from CODE_LAB.md Exercise 4.4):
    - Each user has a monthly budget (default $10)
    - Track spending in Redis, key = budget:<user_id>:<YYYY-MM>
    - Reset at start of next month (key expires after 32 days)
    - Global budget prevents total runaway cost
    """

    def __init__(
        self,
        monthly_budget_usd: float = 10.0,
        global_monthly_budget_usd: float = 100.0,
    ):
        self.monthly_budget_usd = monthly_budget_usd
        self.global_monthly_budget_usd = global_monthly_budget_usd

    def _month_key(self, prefix: str, user_id: str) -> str:
        month = time.strftime("%Y-%m")
        return f"{prefix}:{user_id}:{month}"

    def _get_cost(self, key: str) -> float:
        if USE_REDIS:
            val = _redis.get(key)
            return float(val) if val else 0.0
        return _memory_store.get(key, 0.0)

    def _add_cost(self, key: str, amount: float):
        if USE_REDIS:
            _redis.incrbyfloat(key, amount)
            _redis.expire(key, 32 * 24 * 3600)  # 32 days — auto reset monthly
        else:
            _memory_store[key] = self._get_cost(key) + amount

    def check_budget(self, user_id: str) -> None:
        """
        Raise HTTP 402 if user or global budget exceeded.
        Called BEFORE processing the request.
        """
        global_key = self._month_key("budget", "global")
        global_cost = self._get_cost(global_key)
        if global_cost >= self.global_monthly_budget_usd:
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to global budget limits.",
            )

        user_key = self._month_key("budget", user_id)
        user_cost = self._get_cost(user_key)
        if user_cost >= self.monthly_budget_usd:
            raise HTTPException(
                status_code=402,
                detail=f"Monthly budget of ${self.monthly_budget_usd:.2f} exceeded. "
                       "Resets next month.",
            )

    def record_usage(
        self, user_id: str, input_tokens: int, output_tokens: int
    ) -> float:
        """
        Record token usage cost AFTER a successful LLM call.
        Returns cumulative user spend for this month (USD).
        """
        cost = (
            input_tokens / 1000 * PRICE_PER_1K_INPUT_TOKENS
            + output_tokens / 1000 * PRICE_PER_1K_OUTPUT_TOKENS
        )

        user_key = self._month_key("budget", user_id)
        global_key = self._month_key("budget", "global")

        self._add_cost(user_key, cost)
        self._add_cost(global_key, cost)

        total = self._get_cost(user_key)
        logger.info(
            f"Cost recorded: user={user_id} cost=${cost:.6f} "
            f"monthly_total=${total:.6f}"
        )
        return total

    def get_usage(self, user_id: str) -> dict:
        """Return current month usage info for a user."""
        user_key = self._month_key("budget", user_id)
        spent = self._get_cost(user_key)
        return {
            "spent_usd": round(spent, 6),
            "budget_usd": self.monthly_budget_usd,
            "remaining_usd": round(max(self.monthly_budget_usd - spent, 0), 6),
        }


cost_guard = CostGuard(
    monthly_budget_usd=settings.MONTHLY_BUDGET_USD,
    global_monthly_budget_usd=settings.MONTHLY_BUDGET_USD * 10,
)
