"""git worktree 管理モジュール。

git-worktree-runner (gtr) がインストールされている場合は gtr を使用し、
インストールされていない場合は通常の git worktree コマンドにフォールバックする。

gtr: https://github.com/coderabbitai/git-worktree-runner
"""

import asyncio
import logging
import os
import re
import subprocess

from src.models.workspace import WorktreeInfo

logger = logging.getLogger(__name__)


class WorktreeManager:
    """git worktree を管理するクラス。

    gtr (git-worktree-runner) がインストールされている場合は gtr を優先使用する。
    """

    def __init__(self, repo_path: str, use_gtr: bool | None = None) -> None:
        """WorktreeManagerを初期化する。

        Args:
            repo_path: メインリポジトリのパス
            use_gtr: gtrを使用するか（None の場合は自動検出）
        """
        self.repo_path = repo_path
        self._gtr_available: bool | None = None
        self._force_gtr = use_gtr

    async def _check_gtr_available(self) -> bool:
        """gtr がインストールされているか確認する。"""
        if self._gtr_available is not None:
            return self._gtr_available

        if self._force_gtr is not None:
            self._gtr_available = self._force_gtr
            return self._gtr_available

        # git gtr --version を実行して確認
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "gtr", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            self._gtr_available = proc.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"gtr 検出をスキップ: {e}")
            self._gtr_available = False

        if self._gtr_available:
            logger.info("gtr (git-worktree-runner) を使用します")
        else:
            logger.info("gtr が見つかりません。通常の git worktree を使用します")

        return self._gtr_available

    async def _run_command(
        self, *args: str, cwd: str | None = None
    ) -> tuple[int, str, str]:
        """コマンドを実行する。

        Args:
            *args: コマンドと引数
            cwd: 作業ディレクトリ（省略時はrepo_path）

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        work_dir = cwd or self.repo_path
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except FileNotFoundError:
            return 1, "", f"コマンドが見つかりません: {args[0]}"
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"コマンド実行エラー: {e}")
            return 1, "", str(e)

    async def _run_git(
        self, *args: str, cwd: str | None = None
    ) -> tuple[int, str, str]:
        """gitコマンドを実行する。

        Args:
            *args: gitコマンドの引数
            cwd: 作業ディレクトリ（省略時はrepo_path）

        Returns:
            (リターンコード, stdout, stderr) のタプル
        """
        return await self._run_command("git", *args, cwd=cwd)

    async def is_git_repo(self) -> bool:
        """リポジトリが有効なgitリポジトリか確認する。

        Returns:
            有効なgitリポジトリの場合True
        """
        code, _, _ = await self._run_git("rev-parse", "--git-dir")
        return code == 0

    async def is_gtr_available(self) -> bool:
        """gtr が利用可能か確認する。

        Returns:
            gtr が利用可能な場合True
        """
        return await self._check_gtr_available()

    async def create_worktree(
        self,
        path: str,
        branch: str,
        create_branch: bool = True,
        base_branch: str | None = None,
    ) -> tuple[bool, str, str | None]:
        """新しいworktreeを作成する。

        gtr がインストールされている場合は gtr を使用する。

        Args:
            path: worktreeのパス（gtr使用時は無視され、gtrのデフォルトパスが使用される）
            branch: ブランチ名
            create_branch: 新しいブランチを作成するか
            base_branch: 新しいブランチの基点となるブランチ（省略時はHEAD）

        Returns:
            (成功フラグ, メッセージ, 実際のworktreeパス) のタプル
        """
        use_gtr = await self._check_gtr_available()

        if use_gtr:
            return await self._create_worktree_gtr(branch, base_branch)
        else:
            return await self._create_worktree_native(
                path, branch, create_branch, base_branch
            )

    async def _create_worktree_gtr(
        self,
        branch: str,
        base_branch: str | None = None,
    ) -> tuple[bool, str, str | None]:
        """gtr を使用してworktreeを作成する。

        Args:
            branch: ブランチ名
            base_branch: 基点ブランチ

        Returns:
            (成功フラグ, メッセージ, 実際のworktreeパス) のタプル
        """
        args = ["git", "gtr", "new", branch]

        if base_branch:
            # --from オプションで基点ブランチを指定
            args.extend(["--from", base_branch])

        code, stdout, stderr = await self._run_command(*args)

        if code != 0:
            logger.error(f"gtr worktree作成エラー: {stderr}")
            return False, f"worktree作成に失敗しました: {stderr}", None

        # gtr が作成した実際のパスを取得
        actual_path = await self.get_worktree_path_for_branch(branch)

        logger.info(f"gtr でworktreeを作成しました: {branch} ({actual_path})")
        return True, f"worktreeを作成しました (gtr): {branch}", actual_path

    async def _create_worktree_native(
        self,
        path: str,
        branch: str,
        create_branch: bool = True,
        base_branch: str | None = None,
    ) -> tuple[bool, str, str | None]:
        """通常のgit worktreeコマンドでworktreeを作成する。

        Args:
            path: worktreeのパス
            branch: ブランチ名
            create_branch: 新しいブランチを作成するか
            base_branch: 基点ブランチ

        Returns:
            (成功フラグ, メッセージ, 実際のworktreeパス) のタプル
        """
        if os.path.exists(path):
            return False, f"パスが既に存在します: {path}", None

        args = ["worktree", "add"]

        if create_branch:
            args.extend(["-b", branch])
            args.append(path)
            if base_branch:
                args.append(base_branch)
        else:
            args.append(path)
            args.append(branch)

        code, stdout, stderr = await self._run_git(*args)

        if code != 0:
            logger.error(f"worktree作成エラー: {stderr}")
            return False, f"worktree作成に失敗しました: {stderr}", None

        logger.info(f"worktreeを作成しました: {path} ({branch})")
        return True, f"worktreeを作成しました: {path}", path

    async def remove_worktree(
        self, path_or_branch: str, force: bool = False
    ) -> tuple[bool, str]:
        """worktreeを削除する。

        gtr がインストールされている場合は gtr rm を使用する。

        Args:
            path_or_branch: 削除するworktreeのパスまたはブランチ名
            force: 強制削除するか

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        use_gtr = await self._check_gtr_available()

        if use_gtr:
            return await self._remove_worktree_gtr(path_or_branch, force)
        else:
            return await self._remove_worktree_native(path_or_branch, force)

    async def _remove_worktree_gtr(
        self, path_or_branch: str, force: bool = False
    ) -> tuple[bool, str]:
        """gtr を使用してworktreeを削除する。

        Args:
            path_or_branch: worktree パスまたはブランチ名
            force: 強制削除するか

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        branch = await self._resolve_branch_for_gtr(path_or_branch)
        args = ["git", "gtr", "rm", branch]
        if force:
            args.append("--force")

        code, stdout, stderr = await self._run_command(*args)

        if code != 0:
            logger.error(f"gtr worktree削除エラー: {stderr}")
            return False, f"worktree削除に失敗しました: {stderr}"

        logger.info(f"gtr でworktreeを削除しました: {branch} (input={path_or_branch})")
        return True, f"worktreeを削除しました (gtr): {branch}"

    async def _resolve_branch_for_gtr(self, path_or_branch: str) -> str:
        """gtr rm 用に path 指定から branch を解決する。"""
        normalized = os.path.realpath(path_or_branch)
        for wt in await self.list_worktrees():
            if os.path.realpath(wt.path) == normalized:
                return wt.branch
        return path_or_branch

    @staticmethod
    def _is_worker_branch(branch_name: str | None) -> bool:
        """cleanup 対象となる worker 系ブランチかを判定する。"""
        if not branch_name:
            return False
        if branch_name.startswith("worker-"):
            return True
        return bool(re.match(r"^feature/.+-worker-\d+-[0-9a-z]+$", branch_name))

    async def _remove_worktree_native(
        self, path: str, force: bool = False
    ) -> tuple[bool, str]:
        """通常のgit worktreeコマンドでworktreeを削除する。

        gtr と同様に、worktree 削除後にブランチも削除する。

        Args:
            path: worktreeのパス
            force: 強制削除するか

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        # worktree からブランチ名を取得（削除前に取得）
        branch_name = None
        worktrees = await self.list_worktrees()
        for wt in worktrees:
            if wt.path == path:
                branch_name = wt.branch
                break

        # worktree を削除
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(path)

        code, stdout, stderr = await self._run_git(*args)

        if code != 0:
            logger.error(f"worktree削除エラー: {stderr}")
            return False, f"worktree削除に失敗しました: {stderr}"

        logger.info(f"worktreeを削除しました: {path}")

        # ブランチも削除（gtr と同様の動作）
        branch_deleted = False
        if self._is_worker_branch(branch_name):
            delete_args = ["branch", "-D", branch_name]
            branch_code, _, branch_stderr = await self._run_git(*delete_args)
            if branch_code == 0:
                logger.info(f"ブランチを削除しました: {branch_name}")
                branch_deleted = True
            else:
                logger.warning(f"ブランチ削除に失敗: {branch_name} - {branch_stderr}")

        if branch_deleted:
            return True, f"worktreeとブランチを削除しました: {path} ({branch_name})"
        return True, f"worktreeを削除しました: {path}"

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """worktree一覧を取得する。

        gtr の有無に関わらず git worktree list を使用する。

        Returns:
            WorktreeInfo のリスト
        """
        code, stdout, stderr = await self._run_git("worktree", "list", "--porcelain")

        if code != 0:
            logger.error(f"worktree一覧取得エラー: {stderr}")
            return []

        worktrees: list[WorktreeInfo] = []
        current: dict[str, str] = {}

        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                if current:
                    worktrees.append(self._parse_worktree_info(current))
                    current = {}
                continue

            if " " in line:
                key, value = line.split(" ", 1)
                current[key] = value
            else:
                current[line] = "true"

        if current:
            worktrees.append(self._parse_worktree_info(current))

        return worktrees

    def _parse_worktree_info(self, data: dict[str, str]) -> WorktreeInfo:
        """worktree情報をパースする。

        Args:
            data: パース済みのworktreeデータ

        Returns:
            WorktreeInfo オブジェクト
        """
        return WorktreeInfo(
            path=data.get("worktree", ""),
            branch=data.get("branch", "").replace("refs/heads/", ""),
            commit=data.get("HEAD", ""),
            is_bare="bare" in data,
            is_detached="detached" in data,
            locked="locked" in data,
            prunable="prunable" in data,
        )

    async def open_with_ai(self, branch: str) -> tuple[bool, str]:
        """gtr ai コマンドでworktreeをAIツール（AI CLI）で開く。

        Args:
            branch: ブランチ名

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        use_gtr = await self._check_gtr_available()

        if not use_gtr:
            return False, "gtr がインストールされていません"

        code, stdout, stderr = await self._run_command("git", "gtr", "ai", branch)

        if code != 0:
            return False, f"gtr ai の実行に失敗しました: {stderr}"

        return True, f"AIツールでworktreeを開きました: {branch}"

    async def open_with_editor(self, branch: str) -> tuple[bool, str]:
        """gtr editor コマンドでworktreeをエディタで開く。

        Args:
            branch: ブランチ名

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        use_gtr = await self._check_gtr_available()

        if not use_gtr:
            return False, "gtr がインストールされていません"

        code, stdout, stderr = await self._run_command("git", "gtr", "editor", branch)

        if code != 0:
            return False, f"gtr editor の実行に失敗しました: {stderr}"

        return True, f"エディタでworktreeを開きました: {branch}"

    async def get_worktree_status(self, path: str) -> dict[str, str | int]:
        """指定worktreeのgitステータスを取得する。

        Args:
            path: worktreeのパス

        Returns:
            ステータス情報の辞書
        """
        # ブランチ名を取得
        code, branch, _ = await self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=path
        )
        branch = branch.strip() if code == 0 else "unknown"

        # 変更ファイル数を取得
        code, status, _ = await self._run_git("status", "--porcelain", cwd=path)
        lines = [line for line in status.strip().split("\n") if line]
        changed_files = len(lines) if code == 0 else 0

        # 最新コミットを取得
        code, commit, _ = await self._run_git(
            "rev-parse", "--short", "HEAD", cwd=path
        )
        commit = commit.strip() if code == 0 else "unknown"

        return {
            "path": path,
            "branch": branch,
            "commit": commit,
            "changed_files": changed_files,
        }

    async def prune_worktrees(self) -> tuple[int, str]:
        """削除可能なworktree情報をクリーンアップする。

        Returns:
            (削除数, メッセージ) のタプル
        """
        code, stdout, stderr = await self._run_git("worktree", "prune")

        if code != 0:
            return 0, f"prune失敗: {stderr}"

        return 0, "worktree情報をクリーンアップしました"

    async def get_current_branch(self, path: str | None = None) -> str:
        """現在のブランチ名を取得する。

        Args:
            path: 作業ディレクトリ（省略時はrepo_path）

        Returns:
            ブランチ名
        """
        code, stdout, _ = await self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=path
        )
        return stdout.strip() if code == 0 else ""

    async def fetch(self, remote: str = "origin") -> tuple[bool, str]:
        """リモートから最新情報を取得する。

        Args:
            remote: リモート名

        Returns:
            (成功フラグ, メッセージ) のタプル
        """
        code, stdout, stderr = await self._run_git("fetch", remote)
        if code != 0:
            return False, f"fetch失敗: {stderr}"
        return True, "fetchが完了しました"

    async def get_worktree_path_for_branch(self, branch: str) -> str | None:
        """指定ブランチのworktreeパスを取得する。

        Args:
            branch: ブランチ名

        Returns:
            worktreeのパス、見つからない場合はNone
        """
        worktrees = await self.list_worktrees()
        for wt in worktrees:
            if wt.branch == branch:
                return wt.path
        return None
