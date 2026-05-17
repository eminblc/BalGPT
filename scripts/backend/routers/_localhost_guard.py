"""Ortak localhost erişim kontrolü — desktop_router ve browser_router tarafından kullanılır."""

from ipaddress import AddressValueError, ip_address

from starlette.requests import Request


def is_localhost(request: Request) -> bool:
    """Gelen isteğin yalnızca localhost'tan gelip gelmediğini kontrol eder.

    SEC-SCAN2-R18: ipaddress modülü ile tüm IPv4/IPv6 loopback varyantları
    otomatik olarak kapsanır. Önceki string karşılaştırması aşağıdaki
    varyantları kaçırıyordu:
      - 0:0:0:0:0:0:0:1  (tam IPv6 loopback yazımı)
      - 0:0:0:0:0:ffff:7f00:1  (IPv4-mapped loopback)
      - localhost (string olarak gelse de nadiren görülür)

    ip_address(host).is_loopback tüm RFC-varyantlarını Python standart
    kütüphanesi ile doğrular; yeni varyantlar için güncelleme gerekmez.
    """
    host = request.client.host if request.client else ""
    if not host:
        return False
    try:
        addr = ip_address(host)
        if addr.is_loopback:
            return True
        # IPv4-mapped IPv6 adresleri (::ffff:127.x.x.x): Python'ın ipaddress modülü
        # bunları loopback saymaz; ipv4_mapped özelliğiyle altta yatan IPv4 kontrol edilir.
        mapped = getattr(addr, "ipv4_mapped", None)
        return bool(mapped and mapped.is_loopback)
    except AddressValueError:
        # Geçersiz IP formatı (örn. "localhost" string'i) — güvenli fallback: reddet
        return False
