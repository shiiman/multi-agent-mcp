"""ワークスペース・Worktreeモデル定義。"""

from datetime import datetime

from pydantic import BaseModel, Field


class WorktreeInfo(BaseModel):
    """git worktree 情報。"""

    path: str = Field(description="worktreeのパス")
    branch: str = Field(description="ブランチ名")
    commit: str = Field(description="現在のコミットハッシュ")
    is_bare: bool = Field(default=False, description="bareリポジトリかどうか")
    is_detached: bool = Field(default=False, description="detached HEADかどうか")
    locked: bool = Field(default=False, description="ロックされているかどうか")
    prunable: bool = Field(default=False, description="削除可能かどうか")


class Workspace(BaseModel):
    """ワークスペース情報。"""

    name: str = Field(description="ワークスペース名")
    base_path: str = Field(description="ベースディレクトリのパス")
    repo_path: str = Field(description="メインリポジトリのパス")
    worktrees: list[WorktreeInfo] = Field(default_factory=list, description="worktree一覧")
    created_at: datetime = Field(description="作成日時")


class WorktreeAssignment(BaseModel):
    """エージェントへのworktree割り当て情報。"""

    agent_id: str = Field(description="エージェントID")
    worktree_path: str = Field(description="割り当てられたworktreeのパス")
    branch: str = Field(description="作業ブランチ名")
    assigned_at: datetime = Field(description="割り当て日時")
