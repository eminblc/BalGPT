"""Ortak localhost erişim kontrolü — desktop_router ve browser_router tarafından kullanılır."""

from starlette.requests import Request


def is_localhost(request: Request) -> bool:
    """Gelen isteğin yalnızca localhost'tan gelip gelmediğini kontrol eder."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
