"""MsgpackSerializer — BackupSerializer protokolünü uygular.

SRP: Yalnızca msgpack ile serileştirme/deserileştirme işlemi yapar.
DIP: BackupSerializer protokolünü karşılar; üst katmanlar bu soyutlamaya bağlıdır.
"""
from __future__ import annotations

import msgpack

from ._protocol import BackupSerializer as BackupSerializerProtocol


class MsgpackSerializer:
    """msgpack ile dict ↔ bytes dönüşümü sağlar.

    BackupSerializer protokolünü tam olarak karşılar.
    Bağımlılık enjeksiyonu ile BackupWriter / BackupReader'a verilir.
    """

    def serialize(self, data: dict) -> bytes:
        """Python dict → msgpack bytes.

        use_bin_type=True: Python str → msgpack str; bytes → msgpack bin.
        """
        return msgpack.packb(data, use_bin_type=True)

    def deserialize(self, raw: bytes) -> dict:
        """msgpack bytes → Python dict.

        raw=False: msgpack str → Python str (bytes yerine).
        """
        return msgpack.unpackb(raw, raw=False)


# ---------------------------------------------------------------------------
# Runtime protokol kontrolü — geliştirme sırasında erken hata yakalar
# ---------------------------------------------------------------------------
assert isinstance(MsgpackSerializer(), BackupSerializerProtocol), (
    "MsgpackSerializer BackupSerializer protokolünü karşılamıyor"
)
