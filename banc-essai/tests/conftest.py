import os
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True  # n'écrit rien dans nexus-core/ quand on importe ses règles
BANC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BANC))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def banc():
    return BANC


@pytest.fixture
def missions():
    import noter
    return noter.charger_missions(str(BANC / "missions.json"))


@pytest.fixture
def audit():
    import noter
    return noter.charger_missions(str(BANC / "audit-syfer" / "missions.json"))


@pytest.fixture
def env_propre(tmp_path):
    """Environnement minimal pour lancer.sh (aucune variable NEXUS_* héritée)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NEXUS_", "FONCTIONNEMENT", "SELECTION",
                                                                      "MISSIONS", "FORCER_F4", "ENV_FILE"))}
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    env.update(TMPDIR=str(tmp), INTERVALLE_S="1", ENV_FILE=str(tmp_path / "absent.env"))
    return env
