#!/usr/bin/env python3
"""LLM destekli syntax hata düzeltici — Docker entrypoint'ten çağrılır.

Kullanım:
    python /docker/llm_fix.py --error "SyntaxError: ..." --file path/to/file.py
    python /docker/llm_fix.py --error "SyntaxError: ..." --file path/to/file.py --apply

Çıkış kodu:
    0 → düzeltme uygulandı (--apply) veya öneri yazdırıldı
    1 → API erişilemez veya düzeltme üretilemedi
    2 → düzeltme üretildi ama dosya read-only (image'a baked, volume yok)
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap


def _call_anthropic(error: str, file_path: str, file_content: str) -> str | None:
    """Anthropic API'ye hata + dosya içeriğini gönderir, düzeltilmiş içeriği alır."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        print("  [⚠] anthropic paketi bulunamadı — LLM analizi atlanıyor", flush=True)
        return None

    lang = "python" if file_path.endswith(".py") else "javascript"
    client = anthropic.Anthropic(api_key=api_key)

    prompt = textwrap.dedent(f"""\
        Aşağıdaki {lang} dosyasında bir syntax hatası var.

        HATA:
        {error}

        DOSYA ({file_path}):
        ```{lang}
        {file_content}
        ```

        Görevi:
        1. Hatanın tam nedenini tek cümleyle açıkla.
        2. Düzeltilmiş dosyanın TAMAMI'nı (yorum veya açıklama eklemeden) döndür.

        Yanıt formatı:
        NEDEN: <tek satır açıklama>
        DÜZELTME:
        ```{lang}
        <dosyanın tamamı>
        ```
    """)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as exc:
        print(f"  [⚠] Anthropic API hatası: {exc}", flush=True)
        return None


def _parse_response(response: str, lang: str) -> tuple[str, str]:
    """LLM yanıtından 'neden' açıklaması ve düzeltilmiş kodu ayıklar."""
    reason = ""
    fixed_code = ""

    for line in response.splitlines():
        if line.startswith("NEDEN:"):
            reason = line[len("NEDEN:"):].strip()
            break

    fence = f"```{lang}"
    in_block = False
    code_lines: list[str] = []
    for line in response.splitlines():
        if line.strip() == fence:
            in_block = True
            continue
        if in_block:
            if line.strip() == "```":
                break
            code_lines.append(line)
    fixed_code = "\n".join(code_lines)

    return reason, fixed_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--error", required=True)
    parser.add_argument("--file",  required=True)
    parser.add_argument("--apply", action="store_true",
                        help="Düzeltmeyi dosyaya yaz (dosya yazılabilirse)")
    args = parser.parse_args()

    file_path = args.file
    lang = "python" if file_path.endswith(".py") else "javascript"

    # Dosyayı oku
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        print(f"  [✗] Dosya okunamadı ({file_path}): {exc}", flush=True)
        return 1

    print(f"  [→] LLM'e gönderiliyor: {file_path}", flush=True)
    response = _call_anthropic(args.error, file_path, content)
    if not response:
        print("  [✗] LLM yanıt üretemedi", flush=True)
        return 1

    reason, fixed_code = _parse_response(response, lang)

    if not fixed_code.strip():
        print("  [✗] LLM düzeltme kodu üretemedi — ham yanıt:", flush=True)
        print(response, flush=True)
        return 1

    # Her zaman nedeni yazdır
    if reason:
        print(f"\n  [!] NEDEN: {reason}", flush=True)

    if not args.apply:
        # Sadece göster
        print(f"\n  [→] Önerilen düzeltme ({file_path}):", flush=True)
        print("  " + "-" * 60, flush=True)
        for line in fixed_code.splitlines():
            print(f"  {line}", flush=True)
        print("  " + "-" * 60, flush=True)
        print("\n  Düzeltmeyi uygulamak için --apply bayrağını kullan", flush=True)
        return 0

    # --apply: dosyaya yaz
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
            if not fixed_code.endswith("\n"):
                f.write("\n")
        print(f"  [✓] Düzeltme uygulandı: {file_path}", flush=True)
        return 0
    except OSError:
        # Dosya read-only (image'a baked, volume mount yok)
        print(f"\n  [⚠] Dosya yazılamadı — image'a baked (volume mount yok).", flush=True)
        print(f"  [→] Host'taki dosyayı şu şekilde düzelt ({file_path}):", flush=True)
        print("  " + "-" * 60, flush=True)
        for line in fixed_code.splitlines():
            print(f"  {line}", flush=True)
        print("  " + "-" * 60, flush=True)
        print("\n  Sonra: docker compose build && docker compose up", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
