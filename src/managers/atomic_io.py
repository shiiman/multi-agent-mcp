"""ファイルへのアトミック書き込みユーティリティ。

mkstemp → fsync → chmod → os.replace の順で、書き込み途中の破損やレース時の
中途半端な内容を避ける。tools/managers の双方から利用される下位ユーティリティのため、
標準ライブラリと ``src.config.constants``（定数のみ）に依存し、
他層（managers/tools の実装）は import しない。
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.config.constants import PRIVATE_FILE_MODE


def atomic_write_text(
    file_path: Path,
    content: str,
    *,
    mode: int | None = PRIVATE_FILE_MODE,
    fsync: bool = True,
    mkdir: bool = True,
) -> None:
    """テキストをアトミックに書き込む。

    Args:
        file_path: 書き込み先パス
        content: 書き込む文字列
        mode: 設定する権限（None の場合は chmod を行わない）
        fsync: True の場合 fsync でディスク同期する
        mkdir: True の場合、親ディレクトリを作成する
    """
    if mkdir:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(file_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, str(file_path))
        if mode is not None:
            os.chmod(file_path, mode)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    file_path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int = 2,
    default: Any = str,
    mode: int | None = PRIVATE_FILE_MODE,
    fsync: bool = True,
    mkdir: bool = True,
) -> None:
    """JSON をアトミックに書き込む（atomic_write_text の薄いラッパー）。

    Args:
        file_path: 書き込み先パス
        payload: 書き込む JSON シリアライズ可能なオブジェクト
        ensure_ascii: True の場合、非 ASCII 文字をエスケープする
        indent: JSON のインデント幅
        default: シリアライズ不能なオブジェクトの変換関数（既定は str）
        mode: 設定する権限（None の場合は chmod を行わない）
        fsync: True の場合 fsync でディスク同期する
        mkdir: True の場合、親ディレクトリを作成する
    """
    content = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent, default=default)
    atomic_write_text(file_path, content, mode=mode, fsync=fsync, mkdir=mkdir)
