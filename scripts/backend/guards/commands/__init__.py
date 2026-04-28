"""Owner komutları — registry tabanlı (OCP).

Yeni komut eklemek için:
  1. Yeni dosya oluştur (örn. my_cmd.py)
  2. Command Protocol'ünü uygula
  3. registry.register() çağır
  4. Bu __init__.py'ye import ekle
"""
from .registry import CommandRegistry, Command, registry  # singleton

# Komut modüllerini yükle (yan etki: registry.register() çağrılır)
from . import beta_exit          # noqa: F401, E402
from . import help_cmd           # noqa: F401, E402
from . import history_cmd        # noqa: F401, E402
from . import project_focus_cmd  # noqa: F401, E402
from . import root_reset_cmd     # noqa: F401, E402
from . import restart_cmd        # noqa: F401, E402
from . import shutdown_cmd       # noqa: F401, E402
from . import schedule_cmd       # noqa: F401, E402
from . import root_check_cmd        # noqa: F401, E402
from . import root_log_cmd          # noqa: F401, E402
from . import project_delete_cmd    # noqa: F401, E402
from . import cancel_cmd            # noqa: F401, E402
from . import root_project_cmd      # noqa: F401, E402
from . import root_exit_cmd         # noqa: F401, E402
from . import lang_cmd              # noqa: F401, E402
from . import model_cmd             # noqa: F401, E402
from . import lock_cmd              # noqa: F401, E402
from . import unlock_cmd            # noqa: F401, E402
from . import terminal_cmd          # noqa: F401, E402
from . import timezone_cmd          # noqa: F401, E402
from . import tokens_cmd            # noqa: F401, E402
from . import wizard_cmd            # noqa: F401, E402

__all__ = ["registry", "Command"]
