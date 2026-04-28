from migrate import (
    plan_asset_copies,
    execute_asset_copies,
)


class TestPlanAssetCopies:
    def test_plans_css_and_js(self, registry, tmp_path):
        static = tmp_path / "static"
        copies = plan_asset_copies(registry, static, "/static/")
        sources = {src.name for src, _ in copies}
        assert "Card.css" in sources
        assert "Button.css" in sources
        assert "Button.js" in sources
        assert "Alert.css" in sources

    def test_preserves_prefix_structure(self, registry, tmp_path):
        static = tmp_path / "static"
        copies = plan_asset_copies(registry, static, "/static/")
        dest_strs = {str(dest.relative_to(static)) for _, dest in copies}
        assert "ui/Alert.css" in dest_strs

    def test_deduplicates(self, registry, tmp_path):
        static = tmp_path / "static"
        copies = plan_asset_copies(registry, static, "/static/")
        dests = [dest for _, dest in copies]
        assert len(dests) == len(set(dests))

    def test_skips_missing_assets(self, registry, tmp_path):
        static = tmp_path / "static"
        copies = plan_asset_copies(registry, static, "/static/")
        # Badge has no assets
        sources = {src.name for src, _ in copies}
        assert "Badge.css" not in sources
        assert "Badge.js" not in sources


class TestExecuteAssetCopies:
    def test_copies_files(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "test.css"
        src_file.write_text("body {}")
        dest_file = tmp_path / "dest" / "test.css"

        execute_asset_copies([(src_file, dest_file)], dry_run=False)
        assert dest_file.exists()
        assert dest_file.read_text() == "body {}"

    def test_dry_run_skips(self, tmp_path):
        src_file = tmp_path / "test.css"
        src_file.write_text("body {}")
        dest_file = tmp_path / "dest" / "test.css"

        execute_asset_copies([(src_file, dest_file)], dry_run=True)
        assert not dest_file.exists()

    def test_creates_parent_dirs(self, tmp_path):
        src_file = tmp_path / "test.css"
        src_file.write_text("body {}")
        dest_file = tmp_path / "a" / "b" / "c" / "test.css"

        execute_asset_copies([(src_file, dest_file)], dry_run=False)
        assert dest_file.exists()
