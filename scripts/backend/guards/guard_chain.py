"""Guard zinciri soyutlaması — OCP-1 + DIP-2.

OCP-1: Yeni guard tipi = yeni dosya. Router'a / dispatcher'a dokunulmaz.
DIP-2: GuardChain constructor somut guard örneklerini parametre olarak alır;
       testlerde sahte guard'lar inject edilebilir.

Kullanım:
    from .guard_chain import GuardChain, GuardContext
    from .message_guards import DedupMessageGuard, BlacklistMessageGuard, ...

    _chain = GuardChain([
        DedupMessageGuard(dedup),
        BlacklistMessageGuard(blacklist_mgr),
        OwnerPermissionGuard(perm_mgr, settings),
        RateLimitMessageGuard(rate_limiter),
    ])

    result = await _chain.check(GuardContext(sender, msg_id, msg_type, msg))
    if not result.passed:
        return
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GuardChainMetrics — istatistik state'ini kapsülleyen sınıf (OOP kuralı)
# ---------------------------------------------------------------------------

class GuardChainMetrics:
    """Per-guard ve zincir geneli timing istatistiklerini yönetir.

    OOP uyumu: mutable state sınıf içinde kapsüllenmiş; modül düzeyinde global yok.
    Thread safety: CPython GIL üzerinden sağlanır (mevcut davranışla aynı).
    """

    _LOG_EVERY_N = 50

    def __init__(self) -> None:
        self._guard_stats: Dict[str, dict] = defaultdict(lambda: {
            "count": 0,
            "total_ms": 0.0,
            "min_ms": float("inf"),
            "max_ms": 0.0,
        })
        self._chain_stats: dict = {
            "count": 0, "total_ms": 0.0,
            "min_ms": float("inf"), "max_ms": 0.0,
        }
        self._pass_count: int = 0

    def record_guard(self, name: str, elapsed_ms: float) -> None:
        """Bir guard'ın işlem süresini kaydet."""
        s = self._guard_stats[name]
        s["count"] += 1
        s["total_ms"] += elapsed_ms
        if elapsed_ms < s["min_ms"]:
            s["min_ms"] = elapsed_ms
        if elapsed_ms > s["max_ms"]:
            s["max_ms"] = elapsed_ms

    def record_chain_pass(self, elapsed_ms: float) -> bool:
        """Başarılı bir zincir geçişini kaydet; aggregate log zamanı geldiyse True döndür."""
        self._chain_stats["count"] += 1
        self._chain_stats["total_ms"] += elapsed_ms
        if elapsed_ms < self._chain_stats["min_ms"]:
            self._chain_stats["min_ms"] = elapsed_ms
        if elapsed_ms > self._chain_stats["max_ms"]:
            self._chain_stats["max_ms"] = elapsed_ms
        self._pass_count += 1
        return self._pass_count % self._LOG_EVERY_N == 0

    def get_stats(self) -> dict:
        """Mevcut per-guard timing istatistiklerini döndürür (ortalama dahil).

        Dönen dict örneği::

            {
                "DedupMessageGuard": {
                    "count": 120,
                    "total_ms": 4.8,
                    "min_ms": 0.02,
                    "max_ms": 0.45,
                    "avg_ms": 0.04,
                },
                ...
                "__chain__": { ... }   # tüm zincirin toplamı
            }
        """
        result: dict = {}
        for name, s in self._guard_stats.items():
            avg = s["total_ms"] / s["count"] if s["count"] else 0.0
            result[name] = {**s, "avg_ms": round(avg, 4)}
        cs = self._chain_stats
        chain_avg = cs["total_ms"] / cs["count"] if cs["count"] else 0.0
        result["__chain__"] = {**cs, "avg_ms": round(chain_avg, 4)}
        return result

    def reset(self) -> None:
        """İstatistikleri sıfırlar (test / manuel temizlik için)."""
        self._guard_stats.clear()
        self._chain_stats.update({
            "count": 0, "total_ms": 0.0,
            "min_ms": float("inf"), "max_ms": 0.0,
        })
        self._pass_count = 0


# Modül singleton — GuardChain ve public API buraya delege eder
_metrics = GuardChainMetrics()


# ── Public API (backward-compat) ────────────────────────────────────────────

def get_guard_stats() -> dict:
    """Mevcut per-guard timing istatistiklerini döndürür."""
    return _metrics.get_stats()


def reset_guard_stats() -> None:
    """İstatistikleri sıfırlar (test / manuel temizlik için)."""
    _metrics.reset()


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass
class GuardContext:
    """Her guard'a iletilen mesaj bağlamı."""
    sender:   str
    msg_id:   str
    msg_type: str
    msg:      dict
    lang:     str = field(default="tr")   # Kullanıcı dil tercihi — mesaj_guards için


@dataclass
class GuardResult:
    """Guard kontrol sonucu."""
    passed: bool
    reason: str = field(default="")   # loglama ve debug için


@runtime_checkable
class MessageGuard(Protocol):
    """Tek bir güvenlik kontrolü.

    Her guard kendi side effect'lerini (bildirim, loglama) yönetir.
    passed=False dönünce GuardChain zinciri durdurur; router'a "engellendi" bilgisi iletilir.
    """

    async def check(self, ctx: GuardContext) -> GuardResult: ...


# ---------------------------------------------------------------------------
# GuardChain
# ---------------------------------------------------------------------------


class GuardChain:
    """MessageGuard'ları sırayla çalıştırır; ilk engelde durur.

    DIP-2: Concrete guard örnekleri constructor'dan inject edilir;
    runtime'da gerçek singleton'lar, testlerde sahte nesneler kullanılabilir.

    PERF-3: Her guard'ın işlem süresi ``time.perf_counter()`` ile ölçülür.
    Per-guard istatistikler ``get_guard_stats()`` ile sorgulanabilir.
    Her ``_LOG_EVERY_N`` başarılı zincir geçişinde aggregate INFO logu atılır.
    Bireysel guard süreleri DEBUG seviyesinde loglanır (LOG_LEVEL=DEBUG ile aktif).
    """

    def __init__(self, guards: list[MessageGuard]) -> None:
        self._guards = guards

    async def check(self, ctx: GuardContext) -> GuardResult:
        chain_t0 = time.perf_counter()

        for guard in self._guards:
            guard_name = type(guard).__name__

            t0 = time.perf_counter()
            result = await guard.check(ctx)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            _metrics.record_guard(guard_name, elapsed_ms)
            logger.debug(
                "GuardTiming guard=%s elapsed_ms=%.3f sender=%.6s",
                guard_name, elapsed_ms, ctx.sender,
            )

            if not result.passed:
                logger.debug(
                    "Guard engelledi: guard=%s sender=%.6s reason=%s",
                    guard_name, ctx.sender, result.reason,
                )
                return result

        chain_elapsed_ms = (time.perf_counter() - chain_t0) * 1000.0
        logger.debug("GuardChain total elapsed_ms=%.3f", chain_elapsed_ms)

        should_log = _metrics.record_chain_pass(chain_elapsed_ms)
        if should_log:
            _log_aggregate_stats()

        return GuardResult(passed=True)


def _log_aggregate_stats() -> None:
    """Guard zinciri aggregate istatistiklerini INFO seviyesinde loglar."""
    stats = _metrics.get_stats()
    chain = stats.pop("__chain__", {})
    guard_summary = "; ".join(
        f"{name}(n={s['count']} avg={s['avg_ms']:.3f}ms max={s['max_ms']:.3f}ms)"
        for name, s in stats.items()
    )
    logger.info(
        "GuardChainStats [%d passes] chain_avg=%.3fms chain_max=%.3fms | %s",
        chain.get("count", 0),
        chain.get("avg_ms", 0.0),
        chain.get("max_ms", 0.0),
        guard_summary,
    )
