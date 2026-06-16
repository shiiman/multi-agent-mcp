"""Git ヘルパーの互換ファサード（実体は src.managers.git_utils）。"""

from src.managers.git_utils import *  # noqa: F403
from src.managers.git_utils import (  # noqa: F401  外部が直接 import する非公開名の明示 re-export
    _check_branch_merge_state,
)
