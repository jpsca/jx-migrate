from migrate import create_backup


class TestCreateBackup:
    def test_creates_backup_dir(self, tmp_path):
        src = tmp_path / "test.jinja"
        src.write_text("original")
        backup_path = create_backup([src], [], tmp_path / "backups")
        assert backup_path.exists()
        assert backup_path.is_dir()

    def test_copies_files(self, tmp_path):
        src = tmp_path / "project" / "test.jinja"
        src.parent.mkdir()
        src.write_text("original")
        backup_path = create_backup([src], [], tmp_path / "backups")
        backed_up = list(backup_path.rglob("test.jinja"))
        assert len(backed_up) == 1
        assert backed_up[0].read_text() == "original"

    def test_includes_asset_sources(self, tmp_path):
        asset = tmp_path / "project" / "style.css"
        asset.parent.mkdir()
        asset.write_text("body {}")
        backup_path = create_backup([], [asset], tmp_path / "backups")
        backed_up = list(backup_path.rglob("style.css"))
        assert len(backed_up) == 1

    def test_timestamped_name(self, tmp_path):
        backup_path = create_backup([], [], tmp_path / "backups")
        assert "backup-" in backup_path.name

    def test_skips_nonexistent_files(self, tmp_path):
        missing = tmp_path / "nonexistent.jinja"
        # Should not raise
        backup_path = create_backup([missing], [], tmp_path / "backups")
        assert backup_path.exists()
