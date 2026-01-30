"""AI CLI管理ツール。"""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from src.config.settings import AICli, TerminalApp
from src.context import AppContext
from src.tools.helpers import ensure_cost_manager


def register_tools(mcp: FastMCP) -> None:
    """AI CLI管理ツールを登録する。"""

    @mcp.tool()
    async def get_available_ai_clis(ctx: Context = None) -> dict[str, Any]:
        """利用可能なAI CLI一覧を取得する。

        Returns:
            AI CLI一覧（success, clis, default）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        ai_cli = app_ctx.ai_cli

        return {
            "success": True,
            "clis": ai_cli.get_all_cli_info(),
            "default": ai_cli.get_default_cli().value,
        }

    @mcp.tool()
    async def open_worktree_with_ai_cli(
        worktree_path: str,
        cli: str | None = None,
        prompt: str | None = None,
        terminal: str = "auto",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """指定のAI CLIでworktreeを開く（ターミナルウィンドウを開いて実行）。

        Args:
            worktree_path: worktreeのパス
            cli: 使用するAI CLI（claude/codex/gemini、省略でデフォルト）
            prompt: 初期プロンプト（オプション）
            terminal: 使用するターミナルアプリ（auto/ghostty/iterm2/terminal）

        Returns:
            実行結果（success, cli, terminal, message または error）
        """
        app_ctx: AppContext = ctx.request_context.lifespan_context
        ai_cli_manager = app_ctx.ai_cli

        # CLI の検証
        selected_cli = None
        if cli:
            try:
                selected_cli = AICli(cli)
            except ValueError:
                valid_clis = [c.value for c in AICli]
                return {
                    "success": False,
                    "error": f"無効なAI CLIです: {cli}（有効: {valid_clis}）",
                }

        # ターミナルの検証
        try:
            selected_terminal = TerminalApp(terminal)
        except ValueError:
            valid_terminals = [t.value for t in TerminalApp]
            return {
                "success": False,
                "error": f"無効なターミナルです: {terminal}（有効: {valid_terminals}）",
            }

        success, message = await ai_cli_manager.open_worktree_in_terminal(
            worktree_path, selected_cli, prompt, selected_terminal
        )

        used_cli = selected_cli or ai_cli_manager.get_default_cli()

        # コスト記録
        if success and app_ctx.cost_manager:
            app_ctx.cost_manager.record_call(used_cli.value)

        return {
            "success": success,
            "cli": used_cli.value if success else None,
            "terminal": selected_terminal.value if success else None,
            "worktree_path": worktree_path if success else None,
            "message": message,
        }
