"""
Desktop AT-SPI erişilebilirlik modülü — accessibility tree sorgulama ve element aktivasyonu.

Public API:
    atspi_get_desktop_tree(max_depth) -> dict
    atspi_find_element(role, name) -> list[dict]
    atspi_activate_element(role, name) -> str
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import TYPE_CHECKING

from .desktop_common import _detect_display
from .desktop_input import xdotool_click

logger = logging.getLogger(__name__)


async def _atspi_run_subprocess(script: str, timeout: int = 15) -> str:
    """
    AT-SPI sorgusunu izole bir Python subprocess içinde çalıştırır.

    Atspi.init() yokken SIGABRT/SIGTRAP verebileceğinden ana process yerine
    ayrı bir subprocess kullanılır. JSON çıktısı stdout'tan okunur.

    Args:
        script: Çalıştırılacak Python kodu (print(json.dumps(...)) ile bitmeli).
        timeout: Saniye cinsinden süre sınırı.

    Döner: subprocess stdout (JSON string) veya hata açıklaması.
    """
    python = sys.executable
    # DISPLAY env aktarılır; stderr /dev/null yönlendirilir (GLib uyarıları bastırılır)
    env = {**os.environ, "DISPLAY": _detect_display()}
    proc = await asyncio.create_subprocess_exec(
        python, "-c", script,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return f'{{"error": "AT-SPI subprocess zaman aşımı ({timeout}s)"}}'

    if proc.returncode not in (0, 1):  # SIGABRT → 134, SIGTRAP → 133
        err = stderr.decode(errors="replace")[:300] if stderr else ""
        # AT-SPI bus yok → beklenen hata
        if "Couldn't connect to accessibility bus" in err or "AT-SPI" in err:
            return '{"error": "AT-SPI bus bağlantısı kurulamadı. X11 oturumu ve at-spi-bus-launcher çalışıyor mu?"}'
        return f'{{"error": "AT-SPI subprocess başarısız (kod {proc.returncode})"}}'

    out = stdout.decode(errors="replace").strip() if stdout else ""
    return out if out else '{"error": "AT-SPI subprocess boş çıktı"}'


async def atspi_get_desktop_tree(max_depth: int = 4) -> dict:
    """
    AT-SPI accessibility tree'yi döndürür.

    Desktop → Uygulama → Pencere → Widget hiyerarşisini JSON formatında döndürür.
    Vision API veya ekran görüntüsü gerekmez — doğrudan erişilebilirlik protokolü kullanılır.

    Args:
        max_depth: Ağaç derinliği (1–6). Yüksek değer → daha fazla detay, daha yavaş.

    Döner: {"name": ..., "role": ..., "children": [...]} veya {"error": ...}.

    Kısıtlamalar:
        • AT-SPI bus etkin değilse (DISPLAY'siz headless) hata döner.
        • Electron uygulamaları kısmi destek — bazı elementler görünmeyebilir.
    """
    import json

    # AT-SPI kodunu subprocess'te çalıştıran inline script
    script = f"""
import sys, json
sys.stderr = open('/dev/null', 'w')  # GLib uyarılarını bastır
try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except Exception as e:
    print(json.dumps({{"error": f"gi.repository.Atspi yüklenemedi: {{e}}"}}))
    sys.exit(0)

def node_to_dict(acc, depth, max_depth):
    try:
        name = acc.get_name() or ''
        role = acc.get_role_name() or ''
        role_id = int(acc.get_role())
        child_count = acc.get_child_count()
    except Exception:
        return None
    node = {{"name": name, "role": role, "role_id": role_id, "child_count": child_count}}
    if depth < max_depth and child_count > 0:
        children = []
        for i in range(min(child_count, 50)):
            try:
                child = acc.get_child_at_index(i)
                if child:
                    d = node_to_dict(child, depth + 1, max_depth)
                    if d:
                        children.append(d)
            except Exception:
                pass
        if children:
            node['children'] = children
    return node

try:
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    if desktop is None:
        print(json.dumps({{"name": "desktop", "role": "desktop", "children": [], "note": "desktop None"}}))
        sys.exit(0)
    result = {{"name": desktop.get_name() or "desktop", "role": "desktop", "children": []}}
    for i in range(min(desktop.get_child_count(), 30)):
        try:
            app = desktop.get_child_at_index(i)
            if app:
                d = node_to_dict(app, 1, {max_depth})
                if d:
                    result['children'].append(d)
        except Exception:
            pass
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
    raw = await _atspi_run_subprocess(script, timeout=20)
    try:
        import json as _json
        return _json.loads(raw)
    except Exception:
        logger.error("atspi_get_desktop_tree JSON parse hatası: %r", raw[:200])
        return {"error": f"JSON parse hatası: {raw[:200]}"}


async def atspi_find_element(role: str = "", name: str = "") -> list[dict]:
    """
    AT-SPI tree'de rol ve/veya isimle element arar.

    Args:
        role: AT-SPI rol adı (ör. "push button", "entry", "label"). Boş bırakılırsa yok sayılır.
        name: Element adı (ör. "Tamam", "Kullanıcı adı"). Kısmi eşleşme. Boş bırakılırsa yok sayılır.

    Döner: Eşleşen elementlerin listesi — her biri {role, name, role_id, path}.
    Max 20 sonuç döner.
    """
    if not role and not name:
        return [{"error": "En az 'role' veya 'name' parametrelerinden biri gerekli."}]

    import json as _json

    role_escaped = role.replace("'", "\\'")
    name_escaped = name.replace("'", "\\'")

    script = f"""
import sys, json
sys.stderr = open('/dev/null', 'w')
try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except Exception as e:
    print(json.dumps([{{"error": f"gi.repository.Atspi yüklenemedi: {{e}}"}}]))
    sys.exit(0)

role_lower = '{role_escaped}'.lower().strip()
name_lower = '{name_escaped}'.lower().strip()
results = []

def search(acc, path):
    if len(results) >= 20:
        return
    try:
        acc_role = (acc.get_role_name() or '').lower()
        acc_name = (acc.get_name() or '').lower()
        child_count = acc.get_child_count()
    except Exception:
        return
    role_match = (not role_lower) or (role_lower in acc_role)
    name_match = (not name_lower) or (name_lower in acc_name)
    if role_match and name_match and (role_lower or name_lower):
        results.append({{"role": acc.get_role_name() or '', "name": acc.get_name() or '', "role_id": int(acc.get_role()), "path": path}})
    for i in range(min(child_count, 200)):
        if len(results) >= 20:
            return
        try:
            child = acc.get_child_at_index(i)
            if child:
                search(child, f'{{path}}/{{i}}')
        except Exception:
            pass

try:
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    if desktop:
        for ai in range(min(desktop.get_child_count(), 30)):
            try:
                app = desktop.get_child_at_index(ai)
                if app:
                    search(app, f'/{{ai}}')
            except Exception:
                pass
            if len(results) >= 20:
                break
    print(json.dumps(results))
except Exception as e:
    print(json.dumps([{{"error": str(e)}}]))
"""
    raw = await _atspi_run_subprocess(script, timeout=20)
    try:
        return _json.loads(raw)
    except Exception:
        logger.error("atspi_find_element JSON parse hatası: %r", raw[:200])
        return [{"error": f"JSON parse hatası: {raw[:200]}"}]


async def atspi_activate_element(role: str = "", name: str = "") -> str:
    """
    AT-SPI tree'de element bulur ve aktive eder (tıklar / tetikler).

    Öncelik sırası:
    1. Atspi Action interface → "click" / "press" / "activate" action'ı
    2. İlk mevcut action
    3. Atspi Component → konum alır → xdotool click (fallback)

    Args:
        role: AT-SPI rol adı (ör. "push button").
        name: Element adı (ör. "Tamam"). Kısmi eşleşme.

    Döner: Durum mesajı.
    """
    if not role and not name:
        return "❌ En az 'role' veya 'name' parametrelerinden biri gerekli."

    role_escaped = role.replace("'", "\\'")
    name_escaped = name.replace("'", "\\'")

    script = f"""
import sys, json
sys.stderr = open('/dev/null', 'w')
try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except Exception as e:
    print(json.dumps({{"result": f"ERROR:gi.repository.Atspi yüklenemedi: {{e}}"}}))
    sys.exit(0)

role_lower = '{role_escaped}'.lower().strip()
name_lower = '{name_escaped}'.lower().strip()
found = None

def search(acc):
    global found
    if found is not None:
        return
    try:
        acc_role = (acc.get_role_name() or '').lower()
        acc_name = (acc.get_name() or '').lower()
        child_count = acc.get_child_count()
    except Exception:
        return
    role_match = (not role_lower) or (role_lower in acc_role)
    name_match = (not name_lower) or (name_lower in acc_name)
    if role_match and name_match and (role_lower or name_lower):
        found = acc
        return
    for i in range(min(child_count, 300)):
        if found is not None:
            return
        try:
            child = acc.get_child_at_index(i)
            if child:
                search(child)
        except Exception:
            pass

try:
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    if desktop:
        for ai in range(min(desktop.get_child_count(), 30)):
            try:
                app = desktop.get_child_at_index(ai)
                if app:
                    search(app)
            except Exception:
                pass
            if found is not None:
                break
except Exception as e:
    print(json.dumps({{"result": f"ERROR:{{e}}"}}))
    sys.exit(0)

if found is None:
    print(json.dumps({{"result": f"NOTFOUND:role={{role_lower!r}},name={{name_lower!r}}"}}))
    sys.exit(0)

found_role = found.get_role_name() or '?'
found_name = found.get_name() or ''

# Action interface
try:
    action = found.get_action_iface()
    if action:
        n = action.get_n_actions()
        preferred = ('click', 'press', 'activate', 'jump', 'open')
        for pref in preferred:
            for i in range(n):
                try:
                    act_name = (action.get_action_name(i) or '').lower()
                    if pref in act_name:
                        action.do_action(i)
                        print(json.dumps({{"result": f"OK:{{found_role}}:{{found_name}}:{{action.get_action_name(i)}}"}}))
                        sys.exit(0)
                except Exception:
                    pass
        if n > 0:
            try:
                first = action.get_action_name(0) or 'action[0]'
                action.do_action(0)
                print(json.dumps({{"result": f"OK:{{found_role}}:{{found_name}}:{{first}}"}}))
                sys.exit(0)
            except Exception:
                pass
except Exception:
    pass

# Component fallback
try:
    comp = found.get_component_iface()
    if comp:
        bbox = comp.get_extents(Atspi.CoordType.SCREEN)
        cx = bbox.x + bbox.width // 2
        cy = bbox.y + bbox.height // 2
        print(json.dumps({{"result": f"CLICK_AT:{{cx}},{{cy}}"}}))
        sys.exit(0)
except Exception:
    pass

print(json.dumps({{"result": f"FAILED:{{found_role}}:{{found_name}}"}}))
"""
    raw = await _atspi_run_subprocess(script, timeout=20)
    try:
        import json as _json
        data = _json.loads(raw)
        result = data.get("result", "")
    except Exception:
        logger.error("atspi_activate_element JSON parse hatası: %r", raw[:200])
        return f"❌ AT-SPI JSON parse hatası: {raw[:200]}"

    if result.startswith("OK:"):
        parts = result[3:].split(":", 2)
        found_role = parts[0] if len(parts) > 0 else "?"
        found_name = parts[1] if len(parts) > 1 else ""
        action_name = parts[2] if len(parts) > 2 else "action"
        logger.info("atspi_activate_element: OK role=%r name=%r action=%r", found_role, found_name, action_name)
        return f"✅ Element aktive edildi: role={found_role!r}, name={found_name!r}, action={action_name!r}"

    if result.startswith("CLICK_AT:"):
        coords = result[9:].split(",")
        try:
            cx, cy = int(coords[0]), int(coords[1])
            click_result = await xdotool_click(cx, cy)
            logger.info("atspi_activate_element: xdotool fallback (%d,%d)", cx, cy)
            return f"✅ Element konumuna tıklandı (AT-SPI konum): ({cx},{cy}) — {click_result}"
        except (ValueError, IndexError) as exc:
            return f"❌ AT-SPI koordinat parse hatası: {result!r} — {exc}"

    if result.startswith("NOTFOUND:"):
        info = result[9:]
        return f"❌ Element bulunamadı: {info}"

    if result.startswith("ERROR:"):
        return f"❌ AT-SPI hata: {result[6:]}"

    if result.startswith("FAILED:"):
        info = result[7:]
        return f"❌ Element aktive edilemedi: {info}"

    return f"❌ Beklenmeyen AT-SPI yanıtı: {result[:200]}"
