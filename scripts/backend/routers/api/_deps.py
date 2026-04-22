"""Shared API bağımlılıkları — API key + rate limiter (DRY)."""
from __future__ import annotations

from fastapi import Depends

from ...guards.api_key import require_api_key
from ...guards.api_rate_limiter import require_api_rate_limit

COMMON_DEPS = [Depends(require_api_key), Depends(require_api_rate_limit)]
