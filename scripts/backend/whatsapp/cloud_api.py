"""Meta WhatsApp Cloud API client — mesaj gönderme ve medya indirme."""
import asyncio
import logging
import mimetypes
import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from ..config import settings
from ..constants import (
    WA_MAX_LEN,
    WA_OUTBOUND_TTL,
    WA_IBTN_BODY_MAX,
    WA_LIST_BODY_MAX,
    WA_LIST_BTN_MAX,
    WA_BTN_TITLE_MAX,
    WA_SECTION_TITLE_MAX,
    WA_ROW_TITLE_MAX,
    WA_ROW_DESC_MAX,
    WA_MAX_MEDIA_BYTES,
)

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}"
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def _is_retryable(exc: BaseException) -> bool:
    """H29: 429/503 veya bağlantı hatalarında retry.

    Meta, çift oran sınırı (#131056) için 429 değil HTTP 400 döndürür;
    yanıt gövdesindeki hata kodu kontrol edilerek retry kararı verilir.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (429, 503):
            return True
        if status == 400:
            try:
                code = exc.response.json().get("error", {}).get("code")
                return code == 131056  # Business–Consumer çifti oran sınırı
            except Exception:
                return False
        return False
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException))


_send_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)


# ── Çıkış oranı sınırlayıcı (SEC-RL3) ────────────────────────────
# Aynı alıcıya minimum 1 saniyelik aralık — #131056 rate-limit önleme
_MIN_SEND_INTERVAL = 1.0  # saniye

_outbound_locks: dict[str, asyncio.Lock] = {}
_outbound_last: dict[str, float] = {}


def _evict_outbound(now: float) -> None:
    """TTL süresi geçmiş alıcıları dict'lerden temizle — bellek sızıntısını önler."""
    stale = [k for k, t in _outbound_last.items() if now - t > WA_OUTBOUND_TTL]
    for k in stale:
        _outbound_locks.pop(k, None)
        _outbound_last.pop(k, None)


def evict_outbound_cache() -> None:
    """Süresi dolmuş outbound lock girişlerini temizler (R6).

    Her mesaj gönderiminde `_outbound_lock` zaten lazy-evict yapar; bu fonksiyon
    periyodik temizlik döngüsünden çağrılarak uzun inaktif süreçlerde de temizlik
    garantilenir.
    """
    _evict_outbound(time.monotonic())


def _outbound_lock(to: str) -> asyncio.Lock:
    now = time.monotonic()
    _evict_outbound(now)
    if to not in _outbound_locks:
        _outbound_locks[to] = asyncio.Lock()
    return _outbound_locks[to]


async def _throttle(to: str) -> None:
    """Aynı alıcıya art arda çok hızlı gönderimi engeller."""
    async with _outbound_lock(to):
        now = time.monotonic()
        elapsed = now - _outbound_last.get(to, 0.0)
        if elapsed < _MIN_SEND_INTERVAL:
            await asyncio.sleep(_MIN_SEND_INTERVAL - elapsed)
        _outbound_last[to] = time.monotonic()


def _split_text(text: str, limit: int = WA_MAX_LEN) -> list[str]:
    """Metni WhatsApp limit'ine sığacak parçalara böl; satır sınırlarını koru."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        # limit içinde en son satır sonunu bul
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts



def _check_response(res: httpx.Response, label: str, to: str = "") -> None:
    """Başarısız HTTP yanıtlarını logla ve exception fırlat (K5)."""
    if not res.is_success:
        logger.error("%s başarısız: to=%s status=%d body=%s",
                     label, to, res.status_code, res.text[:200])
        res.raise_for_status()


def _trunc(s: str, limit: int) -> str:
    """Metni Meta limitini aşıyorsa kes ve '…' ekle."""
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _sanitize_sections(sections: list[dict]) -> list[dict]:
    """send_list section/row alanlarını Meta Cloud API limitlerine sığdır."""
    result = []
    for sec in sections:
        rows = []
        for row in sec.get("rows", []):
            sanitized: dict = {
                "id": row["id"],
                "title": _trunc(row["title"], WA_ROW_TITLE_MAX),
            }
            if row.get("description"):
                sanitized["description"] = _trunc(row["description"], WA_ROW_DESC_MAX)
            rows.append(sanitized)
        result.append({
            "title": _trunc(sec.get("title", ""), WA_SECTION_TITLE_MAX),
            "rows": rows,
        })
    return result


@_send_retry
async def send_text(to: str, text: str) -> dict:
    """Kullanıcıya metin mesajı gönder. 4096 karakteri aşan metinler otomatik bölünür."""
    await _throttle(to)
    parts = _split_text(text)
    last_result: dict = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for part in parts:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": part},
            }
            res = await client.post(
                f"{_base_url()}/messages",
                json=payload,
                headers=_headers(),
            )
            _check_response(res, "send_text", to)
            last_result = res.json()
    return last_result


@_send_retry
async def send_buttons(to: str, body: str, buttons: list[dict]) -> dict:
    """
    Tıklanabilir buton mesajı gönder (max 3 buton).
    buttons: [{"id": "btn_id", "title": "Başlık"}, ...]
    """
    await _throttle(to)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": _trunc(body, WA_IBTN_BODY_MAX)},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": _trunc(b["title"], WA_BTN_TITLE_MAX)}}
                    for b in buttons[:3]
                ]
            },
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{_base_url()}/messages",
            json=payload,
            headers=_headers(),
        )
        _check_response(res, "send_buttons", to)
        return res.json()


@_send_retry
async def send_list(to: str, body: str, button_label: str, sections: list[dict]) -> dict:
    """
    Açılır liste menüsü gönder.
    sections: [{"title": "Bölüm", "rows": [{"id": "row_id", "title": "Başlık", "description": "..."}]}]
    """
    await _throttle(to)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": _trunc(body, WA_LIST_BODY_MAX)},
            "action": {
                "button": _trunc(button_label, WA_LIST_BTN_MAX),
                "sections": _sanitize_sections(sections),
            },
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{_base_url()}/messages",
            json=payload,
            headers=_headers(),
        )
        _check_response(res, "send_list", to)
        return res.json()


async def download_media(media_id: str) -> tuple[bytes, str]:
    """
    WhatsApp media_id'den dosyayı indir.
    Döner: (dosya_bytes, mime_type)
    50 MB üzeri dosyalar reddedilir (ValueError).
    """
    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Metadata al (indirme URL'si + mime_type + file_size)
        meta_res = await client.get(
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}",
            headers=_headers(),
        )
        meta_res.raise_for_status()
        meta = meta_res.json()
        url = meta["url"]
        mime_type = meta.get("mime_type", "application/octet-stream")

        # 2. Boyut kontrolü — metadata'daki file_size varsa önden kontrol et
        file_size = meta.get("file_size", 0)
        if file_size and file_size > WA_MAX_MEDIA_BYTES:
            raise ValueError(
                f"Medya boyutu sınırı aşıldı: {file_size} bytes "
                f"(maks {WA_MAX_MEDIA_BYTES // (1024*1024)} MB)"
            )

        # 3. Dosyayı indir
        file_res = await client.get(url, headers=_headers())
        file_res.raise_for_status()

        # 4. İndirme sonrası boyut kontrolü (metadata eksik olabilir)
        if len(file_res.content) > WA_MAX_MEDIA_BYTES:
            raise ValueError(
                f"İndirilen medya boyutu sınırı aşıldı: {len(file_res.content)} bytes"
            )

        logger.info("download_media OK: media_id=%s mime=%s size=%d bytes",
                    media_id, mime_type, len(file_res.content))
        return file_res.content, mime_type


async def get_media_meta(media_id: str) -> dict:
    """Dosyayı indirmeden metadata al (mime_type, file_size, sha256)."""
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}",
            headers=_headers(),
        )
        res.raise_for_status()
        return res.json()


@_send_retry
async def send_image(to: str, image_url: str, caption: str = "") -> dict:
    """URL'den görsel gönder."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{_base_url()}/messages", json=payload, headers=_headers())
        res.raise_for_status()
        logger.info("send_image OK: to=%s", to)
        return res.json()


@_send_retry
async def send_image_by_id(to: str, media_id: str, caption: str = "") -> dict:
    """Daha önce yüklenmiş media_id ile görsel gönder (forward için)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id, "caption": caption},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{_base_url()}/messages", json=payload, headers=_headers())
        res.raise_for_status()
        logger.info("send_image_by_id OK: to=%s media_id=%s", to, media_id)
        return res.json()


@_send_retry
async def send_document_by_id(to: str, media_id: str, filename: str, caption: str = "") -> dict:
    """WhatsApp media_id ile belge gönder."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{_base_url()}/messages", json=payload, headers=_headers())
        res.raise_for_status()
        logger.info("send_document_by_id OK: to=%s media_id=%s", to, media_id)
        return res.json()


@_send_retry
async def send_audio_by_id(to: str, media_id: str) -> dict:
    """WhatsApp media_id ile ses gönder."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{_base_url()}/messages", json=payload, headers=_headers())
        res.raise_for_status()
        logger.info("send_audio_by_id OK: to=%s media_id=%s", to, media_id)
        return res.json()


@_send_retry
async def send_video_by_id(to: str, media_id: str, caption: str = "") -> dict:
    """WhatsApp media_id ile video gönder."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": {"id": media_id, "caption": caption},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{_base_url()}/messages", json=payload, headers=_headers())
        res.raise_for_status()
        logger.info("send_video_by_id OK: to=%s media_id=%s", to, media_id)
        return res.json()


def _mime_to_wa_type(mime_type: str) -> str:
    """MIME type'ı Meta Cloud API medya tipine çevir."""
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "document"


@_send_retry
async def upload_media(file_path: str, mime_type: str | None = None) -> str:
    """Yerel dosyayı Meta Cloud API'ye yükle ve media_id döndür.

    mime_type belirtilmezse dosya uzantısından otomatik tespit edilir.
    Döner: media_id (str)
    """
    if not mime_type:
        guessed, _ = mimetypes.guess_type(file_path)
        mime_type = guessed or "application/octet-stream"

    wa_type = _mime_to_wa_type(mime_type)

    with open(file_path, "rb") as fh:
        file_bytes = fh.read()

    data = {"messaging_product": "whatsapp", "type": wa_type}
    files = {"file": (file_path.rsplit("/", 1)[-1], file_bytes, mime_type)}

    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{_base_url()}/media",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
        res.raise_for_status()
        media_id: str = res.json()["id"]
        logger.info("upload_media OK: path=%s mime=%s media_id=%s", file_path, mime_type, media_id)
        return media_id


async def forward_media_message(
    to: str,
    media_id: str,
    media_type: str,
    caption: str = "",
    filename: str = "file",
) -> dict | None:
    """Gelen medyayı aynı kullanıcıya geri ilet (echo veya onay amacıyla).

    media_type: image | audio | document | video
    """
    try:
        if media_type == "image":
            return await send_image_by_id(to, media_id, caption)
        elif media_type == "document":
            return await send_document_by_id(to, media_id, filename, caption)
        elif media_type == "audio":
            return await send_audio_by_id(to, media_id)
        elif media_type == "video":
            return await send_video_by_id(to, media_id, caption)
        else:
            logger.warning("forward_media_message: bilinmeyen tip %s", media_type)
            return None
    except Exception as exc:
        logger.error("forward_media_message başarısız: %s", exc)
        return None
