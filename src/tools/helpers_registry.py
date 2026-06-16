"""レジストリ・設定 JSON ヘルパーの互換ファサード（実体は src.managers.project_registry）。"""

from src.managers.project_registry import *  # noqa: F403
from src.managers.project_registry import (  # noqa: F401  外部/ファサードが参照する非公開名
    _get_agent_registry_dir,
    _get_from_config,
    _get_global_mcp_dir,
)
