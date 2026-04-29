"""/tokens komutu — LLM token kullanım istatistikleri (TOKEN-STATS-2)."""
from __future__ import annotations

from .registry import registry
from ..permission import Perm

_VALID_SPANS = {"24h": 24, "7d": 168, "30d": 720}


def _fmt(n: int) -> str:
    """Token sayısını okunabilir formata çevirir: 1_234_567 → 1.2M, 12_345 → 12.3K."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class TokensCommand:
    cmd_id      = "/tokens"
    perm        = Perm.OWNER
    button_id   = "cmd_tokens"
    label       = "Token İstatistikleri"
    description = "LLM token kullanım istatistiklerini gösterir. Zaman aralığı: 24h (varsayılan), 7d, 30d."
    usage       = "/tokens [24h|7d|30d]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        from ...store.repositories import token_stat_repo

        lang      = session.get("lang", "tr")
        messenger = get_messenger()

        span_key = arg.strip().lower() or "24h"
        if span_key not in _VALID_SPANS:
            await messenger.send_text(sender, t("tokens.invalid_span", lang, span=span_key))
            return

        hours = _VALID_SPANS[span_key]
        totals  = await token_stat_repo.get_totals(hours)
        summary = await token_stat_repo.get_summary(hours)

        if not totals or not totals.get("calls"):
            await messenger.send_text(sender, t("tokens.empty", lang, span=span_key))
            return

        lines: list[str] = [
            t("tokens.header", lang, span=span_key),
            "",
            t(
                "tokens.total",
                lang,
                input=_fmt(totals.get("input_tokens") or 0),
                output=_fmt(totals.get("output_tokens") or 0),
                calls=totals.get("calls") or 0,
            ),
        ]

        # ── Model kategorileri ────────────────────────────────────────
        model_rows = _group_by_model(summary)
        if model_rows:
            lines.append("")
            lines.append(t("tokens.model_header", lang))
            for row in model_rows:
                lines.append(
                    t(
                        "tokens.model_row",
                        lang,
                        name=row["model_name"],
                        input=_fmt(row["input_tokens"]),
                        output=_fmt(row["output_tokens"]),
                        calls=row["calls"],
                    )
                )

        # ── Backend'ler ───────────────────────────────────────────────
        backend_rows = _group_by_backend(summary)
        if len(backend_rows) > 1:
            lines.append("")
            lines.append(t("tokens.backend_header", lang))
            for row in backend_rows:
                lines.append(
                    t(
                        "tokens.backend_row",
                        lang,
                        name=row["backend"].capitalize(),
                        input=_fmt(row["input_tokens"]),
                        output=_fmt(row["output_tokens"]),
                        calls=row["calls"],
                    )
                )

        await messenger.send_text(sender, "\n".join(lines))


def _group_by_model(summary: list[dict]) -> list[dict]:
    """model_name bazında topla, total_tokens'a göre azalan sırala."""
    merged: dict[str, dict] = {}
    for row in summary:
        name = row["model_name"]
        if name not in merged:
            merged[name] = {"model_name": name, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        merged[name]["calls"]         += row["calls"]
        merged[name]["input_tokens"]  += row["input_tokens"]
        merged[name]["output_tokens"] += row["output_tokens"]
    return sorted(merged.values(), key=lambda r: r["input_tokens"] + r["output_tokens"], reverse=True)


def _group_by_backend(summary: list[dict]) -> list[dict]:
    """backend bazında topla, total_tokens'a göre azalan sırala."""
    merged: dict[str, dict] = {}
    for row in summary:
        be = row["backend"]
        if be not in merged:
            merged[be] = {"backend": be, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        merged[be]["calls"]         += row["calls"]
        merged[be]["input_tokens"]  += row["input_tokens"]
        merged[be]["output_tokens"] += row["output_tokens"]
    return sorted(merged.values(), key=lambda r: r["input_tokens"] + r["output_tokens"], reverse=True)


registry.register(TokensCommand())
