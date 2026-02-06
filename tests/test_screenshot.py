"""スクリーンショット機能のテスト。"""

import base64


class TestScreenshotDirectory:
    """スクリーンショットディレクトリのテスト。"""

    def test_screenshot_dir_structure(self, temp_dir):
        """スクリーンショットディレクトリ構造をテスト。"""
        mcp_dir = temp_dir / ".multi-agent-mcp"
        screenshot_dir = mcp_dir / "screenshot"

        # ディレクトリ作成
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        assert mcp_dir.exists()
        assert screenshot_dir.exists()

    def test_screenshot_file_listing(self, temp_dir):
        """スクリーンショットファイル一覧取得をテスト。"""
        screenshot_dir = temp_dir / ".multi-agent-mcp" / "screenshot"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # テスト用ファイル作成
        (screenshot_dir / "test1.png").write_bytes(b"PNG")
        (screenshot_dir / "test2.jpg").write_bytes(b"JPG")
        (screenshot_dir / "test3.txt").write_text("not an image")

        # 画像ファイルのみ収集
        extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        files = []
        for ext in extensions:
            files.extend(screenshot_dir.glob(f"*{ext}"))

        assert len(files) == 2
        filenames = [f.name for f in files]
        assert "test1.png" in filenames
        assert "test2.jpg" in filenames
        assert "test3.txt" not in filenames


class TestScreenshotReading:
    """スクリーンショット読み取りのテスト。"""

    def test_read_screenshot_base64(self, temp_dir):
        """スクリーンショットを Base64 で読み取れることをテスト。"""
        screenshot_dir = temp_dir / ".multi-agent-mcp" / "screenshot"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # テスト用 PNG ファイル作成（ミニマルなPNGヘッダー）
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        test_file = screenshot_dir / "test.png"
        test_file.write_bytes(png_data)

        # 読み取り
        with open(test_file, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        # デコードして元データと一致することを確認
        decoded = base64.b64decode(data)
        assert decoded == png_data

    def test_mime_type_detection(self):
        """MIME タイプ検出をテスト。"""
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }

        assert mime_map[".png"] == "image/png"
        assert mime_map[".jpg"] == "image/jpeg"
        assert mime_map[".gif"] == "image/gif"

    def test_find_latest_screenshot(self, temp_dir):
        """最新のスクリーンショットを取得できることをテスト。"""
        import time

        screenshot_dir = temp_dir / ".multi-agent-mcp" / "screenshot"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # 古いファイル
        old_file = screenshot_dir / "old.png"
        old_file.write_bytes(b"old")

        time.sleep(0.1)  # タイムスタンプの差を確保

        # 新しいファイル
        new_file = screenshot_dir / "new.png"
        new_file.write_bytes(b"new")

        # 最新ファイルを取得
        files = list(screenshot_dir.glob("*.png"))
        latest = max(files, key=lambda f: f.stat().st_mtime)

        assert latest.name == "new.png"


class TestScreenshotExtensions:
    """スクリーンショット拡張子設定のテスト。"""

    def test_default_extensions(self, settings):
        """デフォルト拡張子が正しいことをテスト。"""
        expected = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        assert settings.screenshot_extensions == expected

    def test_filter_by_extensions(self, temp_dir, settings):
        """拡張子でフィルタできることをテスト。"""
        screenshot_dir = temp_dir / ".multi-agent-mcp" / "screenshot"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # 様々な拡張子のファイルを作成
        (screenshot_dir / "image.png").write_bytes(b"png")
        (screenshot_dir / "image.jpg").write_bytes(b"jpg")
        (screenshot_dir / "image.bmp").write_bytes(b"bmp")  # 対象外
        (screenshot_dir / "document.pdf").write_bytes(b"pdf")  # 対象外

        # 対象拡張子のみ収集
        files = []
        for ext in settings.screenshot_extensions:
            files.extend(screenshot_dir.glob(f"*{ext}"))

        assert len(files) == 2
        filenames = [f.name for f in files]
        assert "image.png" in filenames
        assert "image.jpg" in filenames
        assert "image.bmp" not in filenames
        assert "document.pdf" not in filenames
