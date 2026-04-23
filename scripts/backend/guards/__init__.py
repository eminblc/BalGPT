"""Guards paketi — her modül tek bir güvenlik sorumluluğu taşır (SRP).

Dışarıdan kullanım:
    from .guards import blacklist_mgr, rate_limiter, session_mgr, perm_mgr, dedup, Perm
"""
from .blacklist import BlacklistManager
from .permission import PermissionManager, Perm
from .rate_limiter import RateLimiter
from .session import SessionManager
from .deduplication import DedupGuard
from .runtime_state import record_status, get_last_status
from .output_filter import filter_response
from .capability_guard import CapabilityGuard

blacklist_mgr    = BlacklistManager()
perm_mgr         = PermissionManager()
rate_limiter     = RateLimiter()
session_mgr      = SessionManager()
dedup            = DedupGuard()
capability_guard = CapabilityGuard()  # cfg=None → settings içsel olarak okunur


# ── FastAPI Depends provider'ları (SOLID-DIP2) ───────────────────────────────
# Testlerde `app.dependency_overrides[get_session_mgr] = lambda: mock` şeklinde
# override edilir; singleton'a doğrudan bağımlılık ortadan kalkar.

def get_session_mgr() -> SessionManager:
    return session_mgr


def get_blacklist_mgr() -> BlacklistManager:
    return blacklist_mgr


def get_rate_limiter() -> RateLimiter:
    return rate_limiter


def get_dedup() -> DedupGuard:
    return dedup


def get_perm_mgr() -> PermissionManager:
    return perm_mgr


def get_capability_guard() -> CapabilityGuard:
    return capability_guard


__all__ = [
    "blacklist_mgr", "perm_mgr", "rate_limiter", "session_mgr", "dedup",
    "Perm", "record_status", "get_last_status",
    "filter_response",
    "capability_guard",
    # DI provider'ları
    "get_session_mgr", "get_blacklist_mgr", "get_rate_limiter",
    "get_dedup", "get_perm_mgr", "get_capability_guard",
]
