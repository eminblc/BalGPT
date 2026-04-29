"""GuardChain + MessageGuard implementasyonları testleri (OCP-1 + DIP-2)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.guards.guard_chain import GuardChain, GuardContext, GuardResult
from backend.guards.message_guards import (
    DedupMessageGuard,
    BlacklistMessageGuard,
    OwnerPermissionGuard,
    RateLimitMessageGuard,
)


# ── Yardımcı ──────────────────────────────────────────────────────

def _ctx(sender="905001234567", msg_id="msg-001", msg_type="text", msg=None):
    return GuardContext(
        sender=sender,
        msg_id=msg_id,
        msg_type=msg_type,
        msg=msg or {"type": "text", "text": {"body": "merhaba"}},
    )


class _AlwaysPass:
    async def check(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(passed=True)


class _AlwaysFail:
    async def check(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(passed=False, reason="test_fail")


# ── GuardChain ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_chain_passes():
    result = await GuardChain([]).check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_all_pass_returns_passed():
    chain = GuardChain([_AlwaysPass(), _AlwaysPass()])
    result = await chain.check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_first_fail_stops_chain():
    """İlk engel sonrası sonraki guard çağrılmamalı."""
    called = []

    class _Tracker:
        async def check(self, ctx):
            called.append("tracker")
            return GuardResult(passed=True)

    chain = GuardChain([_AlwaysFail(), _Tracker()])
    result = await chain.check(_ctx())
    assert result.passed is False
    assert result.reason == "test_fail"
    assert "tracker" not in called  # ikinci guard çağrılmadı


@pytest.mark.asyncio
async def test_fail_in_middle_stops_chain():
    called = []

    class _Mark:
        def __init__(self, name, pass_):
            self.name = name
            self.pass_ = pass_
        async def check(self, ctx):
            called.append(self.name)
            return GuardResult(passed=self.pass_)

    chain = GuardChain([_Mark("a", True), _Mark("b", False), _Mark("c", True)])
    result = await chain.check(_ctx())
    assert result.passed is False
    assert called == ["a", "b"]  # "c" çağrılmadı


# ── DedupMessageGuard ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedup_new_message_passes():
    mock_dedup = MagicMock()
    mock_dedup.is_duplicate.return_value = False
    guard = DedupMessageGuard(mock_dedup)
    result = await guard.check(_ctx(msg_id="new-msg"))
    assert result.passed is True


@pytest.mark.asyncio
async def test_dedup_duplicate_message_blocked():
    mock_dedup = MagicMock()
    mock_dedup.is_duplicate.return_value = True
    guard = DedupMessageGuard(mock_dedup)
    result = await guard.check(_ctx(msg_id="dup-msg"))
    assert result.passed is False
    assert result.reason == "duplicate"


# ── BlacklistMessageGuard ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_blacklist_allowed_sender_passes():
    mock_mgr = MagicMock()
    mock_mgr.is_blocked.return_value = False
    guard = BlacklistMessageGuard(mock_mgr)
    result = await guard.check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_blacklist_blocked_sender_fails():
    mock_mgr = MagicMock()
    mock_mgr.is_blocked.return_value = True
    guard = BlacklistMessageGuard(mock_mgr)
    result = await guard.check(_ctx())
    assert result.passed is False
    assert result.reason == "blacklisted"


# ── OwnerPermissionGuard ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_passes():
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = True
    mock_settings = MagicMock()
    guard = OwnerPermissionGuard(mock_perm, mock_settings, AsyncMock())
    result = await guard.check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_non_owner_blocked():
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_settings.whatsapp_owner = None  # bildirim devre dışı
    guard = OwnerPermissionGuard(mock_perm, mock_settings, AsyncMock())
    result = await guard.check(_ctx(sender="999"))
    assert result.passed is False
    assert result.reason == "unauthorized"


@pytest.mark.asyncio
async def test_non_owner_notification_sent_to_owner():
    """Yetkisiz sender'da owner'a bildirim gönderilmeli."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_settings.owner_id = "905550000001"

    mock_messenger = AsyncMock()
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger)
    await guard.check(_ctx(sender="905559999999"))

    mock_messenger.send_text.assert_awaited_once()
    call_args = mock_messenger.send_text.call_args
    assert call_args[0][0] == "905550000001"  # owner'a gönderildi
    assert "905559999999" in call_args[0][1]  # yetkisiz numara mesajda


@pytest.mark.asyncio
async def test_non_owner_notification_failure_does_not_raise():
    """Bildirim gönderimi başarısız olsa bile guard sessizce devam etmeli."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_settings.whatsapp_owner = "905550000001"

    mock_messenger = AsyncMock()
    mock_messenger.send_text.side_effect = Exception("Network error")
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger)
    result = await guard.check(_ctx(sender="905559999999"))

    assert result.passed is False  # hata olsa da unauthorized döner


# ── RateLimitMessageGuard ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_within_limit_passes():
    mock_limiter = MagicMock()
    mock_limiter.check.return_value = True
    guard = RateLimitMessageGuard(mock_limiter, AsyncMock())
    result = await guard.check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_rate_limit_exceeded_fails():
    mock_limiter = MagicMock()
    mock_limiter.check.return_value = False
    mock_messenger = AsyncMock()
    guard = RateLimitMessageGuard(mock_limiter, lambda: mock_messenger)
    result = await guard.check(_ctx())
    assert result.passed is False
    assert result.reason == "rate_limited"
    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_notification_failure_does_not_raise():
    mock_limiter = MagicMock()
    mock_limiter.check.return_value = False
    mock_messenger = AsyncMock()
    mock_messenger.send_text.side_effect = Exception("send failed")
    guard = RateLimitMessageGuard(mock_limiter, lambda: mock_messenger)
    result = await guard.check(_ctx())
    assert result.passed is False


# ── Tam zincir entegrasyonu ───────────────────────────────────────

@pytest.mark.asyncio
async def test_full_chain_all_pass():
    dedup = MagicMock(); dedup.is_duplicate.return_value = False
    bl    = MagicMock(); bl.is_blocked.return_value = False
    perm  = MagicMock(); perm.is_owner.return_value = True
    rl    = MagicMock(); rl.check.return_value = True
    settings = MagicMock()
    mock_messenger = AsyncMock()

    chain = GuardChain([
        DedupMessageGuard(dedup),
        BlacklistMessageGuard(bl),
        OwnerPermissionGuard(perm, settings, lambda: mock_messenger),
        RateLimitMessageGuard(rl, lambda: mock_messenger),
    ])
    result = await chain.check(_ctx())
    assert result.passed is True


@pytest.mark.asyncio
async def test_non_owner_explicit_notification_target_none():
    """notification_target=None olduğunda bildirim gönderilmemeli."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_messenger = AsyncMock()
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger,
                                 notification_target=None)
    result = await guard.check(_ctx(sender="905559999999"))
    assert result.passed is False
    assert result.reason == "unauthorized"
    mock_messenger.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_explicit_notification_target_custom():
    """notification_target açıkça verildiğinde o adrese bildirim gönderilmeli."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_messenger = AsyncMock()
    custom_target = "telegram_chat_12345"
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger,
                                 notification_target=custom_target)
    await guard.check(_ctx(sender="905559999999"))
    mock_messenger.send_text.assert_awaited_once()
    call_args = mock_messenger.send_text.call_args
    assert call_args[0][0] == custom_target  # custom hedefe gönderildi


@pytest.mark.asyncio
async def test_owner_permission_preview_text_body():
    """Mesaj text içerdiğinde bildirimde body preview yer almalı."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_settings.whatsapp_owner = "905550000001"
    mock_messenger = AsyncMock()

    ctx = GuardContext(
        sender="905559999999",
        msg_id="x",
        msg_type="text",
        msg={"text": {"body": "gizli bilgi burada"}},
    )
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger)
    await guard.check(ctx)

    call_args = mock_messenger.send_text.call_args
    notification_text = call_args[0][1]
    assert "gizli bilgi burada" in notification_text


@pytest.mark.asyncio
async def test_owner_permission_preview_type_only():
    """Mesaj text içermiyorsa (image vb.) bildirimde tip etiketi yer almalı."""
    mock_perm = MagicMock()
    mock_perm.is_owner.return_value = False
    mock_settings = MagicMock()
    mock_settings.whatsapp_owner = "905550000001"
    mock_messenger = AsyncMock()

    ctx = GuardContext(
        sender="905559999999",
        msg_id="x",
        msg_type="image",
        msg={"type": "image"},
    )
    guard = OwnerPermissionGuard(mock_perm, mock_settings, lambda: mock_messenger)
    await guard.check(ctx)

    call_args = mock_messenger.send_text.call_args
    notification_text = call_args[0][1]
    assert "[image]" in notification_text


# ── Tam zincir entegrasyonu ───────────────────────────────────────

@pytest.mark.asyncio
async def test_full_chain_dedup_blocks_early():
    dedup = MagicMock(); dedup.is_duplicate.return_value = True
    bl    = MagicMock(); bl.is_blocked.return_value = False
    perm  = MagicMock(); perm.is_owner.return_value = True
    rl    = MagicMock(); rl.check.return_value = True
    settings = MagicMock()
    mock_messenger = AsyncMock()

    chain = GuardChain([
        DedupMessageGuard(dedup),
        BlacklistMessageGuard(bl),
        OwnerPermissionGuard(perm, settings, lambda: mock_messenger),
        RateLimitMessageGuard(rl, lambda: mock_messenger),
    ])
    result = await chain.check(_ctx())
    assert result.passed is False
    assert result.reason == "duplicate"
    bl.is_blocked.assert_not_called()   # sonraki guard'lar çağrılmadı
    perm.is_owner.assert_not_called()
    rl.check.assert_not_called()
