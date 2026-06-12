import time
import logging
from fastapi import HTTPException
import redis
from app.config import settings

logger = logging.getLogger(__name__)

PRICE_PER_1K_INPUT_TOKENS = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006

try:
    _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store = {}

class CostGuard:
    def __init__(self, daily_budget_usd: float = 1.0, global_daily_budget_usd: float = 10.0):
        self.daily_budget_usd = daily_budget_usd
        self.global_daily_budget_usd = global_daily_budget_usd

    def _get_cost(self, key: str) -> float:
        if USE_REDIS:
            val = _redis.get(key)
            return float(val) if val else 0.0
        return _memory_store.get(key, 0.0)
        
    def _add_cost(self, key: str, amount: float):
        if USE_REDIS:
            _redis.incrbyfloat(key, amount)
            _redis.expire(key, 86400 * 2)
        else:
            _memory_store[key] = self._get_cost(key) + amount

    def check_budget(self, user_id: str) -> None:
        today = time.strftime("%Y-%m-%d")
        user_key = f"cost:{user_id}:{today}"
        global_key = f"cost:global:{today}"
        
        global_cost = self._get_cost(global_key)
        if global_cost >= self.global_daily_budget_usd:
            raise HTTPException(status_code=503, detail="Service temporarily unavailable due to global budget limits.")
            
        user_cost = self._get_cost(user_key)
        if user_cost >= self.daily_budget_usd:
            raise HTTPException(status_code=402, detail="Daily budget exceeded")

    def record_usage(self, user_id: str, input_tokens: int, output_tokens: int) -> float:
        today = time.strftime("%Y-%m-%d")
        user_key = f"cost:{user_id}:{today}"
        global_key = f"cost:global:{today}"
        
        cost = (input_tokens / 1000 * PRICE_PER_1K_INPUT_TOKENS +
                output_tokens / 1000 * PRICE_PER_1K_OUTPUT_TOKENS)
                
        self._add_cost(user_key, cost)
        self._add_cost(global_key, cost)
        
        return self._get_cost(user_key)

cost_guard = CostGuard(daily_budget_usd=1.0, global_daily_budget_usd=10.0)
