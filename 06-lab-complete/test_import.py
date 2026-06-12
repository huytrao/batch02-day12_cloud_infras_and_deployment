import sys
sys.path.insert(0, '.')
from app.config import settings
from app.auth import verify_api_key
from app.rate_limiter import rate_limiter_user
from app.cost_guard import cost_guard
from utils.mock_llm import ask
print('✅ All imports OK')
print(f'App: {settings.APP_NAME}')
