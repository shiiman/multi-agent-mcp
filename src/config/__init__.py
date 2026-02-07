"""設定モジュール。"""

from .settings import AICli, Settings
from .templates import (
    TEMPLATES,
    WorkspaceTemplate,
    get_template,
    get_template_names,
    list_templates,
)

__all__ = [
    "TEMPLATES",
    "AICli",
    "Settings",
    "WorkspaceTemplate",
    "get_template",
    "get_template_names",
    "list_templates",
]
