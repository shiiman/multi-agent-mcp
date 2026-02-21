"""プロジェクト共通定数。"""

# ファイルパーミッション: オーナーのみ読み書き可
PRIVATE_FILE_MODE = 0o600

# サブプロセス実行のデフォルトタイムアウト（秒）
SUBPROCESS_TIMEOUT_SECONDS = 30.0

# サブプロセス kill 後の wait タイムアウト（秒）
KILL_WAIT_TIMEOUT_SECONDS = 5.0
