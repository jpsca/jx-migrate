from pathlib import Path

from migrate import (
    add_auto_assets,
    get_asset_url,
    migrate_asset_rendering,
    update_asset_paths,
    ComponentInfo,
)


# =========================================================================
# Phase 3c: Asset Rendering
# =========================================================================


class TestMigrateAssetRendering:
    def test_basic(self):
        source = "{{ catalog.render_assets() }}"
        assert migrate_asset_rendering(source) == "{{ assets.render() }}"

    def test_with_whitespace(self):
        source = "{{  catalog.render_assets()  }}"
        assert migrate_asset_rendering(source) == "{{ assets.render() }}"

    def test_in_html(self):
        source = "<head>\n  {{ catalog.render_assets() }}\n</head>"
        result = migrate_asset_rendering(source)
        assert "{{ assets.render() }}" in result
        assert "catalog" not in result

    def test_other_catalog_calls_unchanged(self):
        source = "{{ catalog.render('Page') }}"
        assert migrate_asset_rendering(source) == source

    def test_no_match_unchanged(self):
        source = "<div>Hello</div>"
        assert migrate_asset_rendering(source) == source


# =========================================================================
# Phase 3d & 3e: Asset Declarations
# =========================================================================


class TestGetAssetUrl:
    def test_no_prefix(self):
        assert get_asset_url("Card.css", "", "/static/components/") == "/static/components/Card.css"

    def test_with_prefix(self):
        assert get_asset_url("Alert.css", "ui", "/static/components/") == "/static/components/ui/Alert.css"

    def test_subfolder(self):
        assert get_asset_url("common/Form.css", "", "/static/") == "/static/common/Form.css"


class TestAddAutoAssets:
    def test_adds_css_when_missing(self):
        source = "{#def title #}\n<div>{{ title }}</div>\n"
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
            has_css=True,
            css_path=Path("/c/Card.css"),
        )
        result = add_auto_assets(source, info, "/static/")
        assert "{#css /static/Card.css #}" in result

    def test_adds_js_when_missing(self):
        source = "{#def label #}\n<button>{{ label }}</button>\n"
        info = ComponentInfo(
            jinjax_name="Button",
            file_path=Path("/c/Button.jinja"),
            rel_path="Button.jinja",
            prefix="",
            import_path="Button.jinja",
            has_js=True,
            js_path=Path("/c/Button.js"),
        )
        result = add_auto_assets(source, info, "/static/")
        assert "{#js /static/Button.js #}" in result

    def test_skips_already_declared(self):
        source = "{#css Button.css #}\n{#def label #}\n"
        info = ComponentInfo(
            jinjax_name="Button",
            file_path=Path("/c/Button.jinja"),
            rel_path="Button.jinja",
            prefix="",
            import_path="Button.jinja",
            has_css=True,
            css_path=Path("/c/Button.css"),
        )
        result = add_auto_assets(source, info, "/static/")
        # Should not add a second css declaration
        assert result.count("{#css") == 1

    def test_no_component_info_returns_unchanged(self):
        source = "<div>Hello</div>"
        assert add_auto_assets(source, None, "/static/") == source

    def test_no_assets_returns_unchanged(self):
        source = "{#def x #}\n<div>{{ x }}</div>\n"
        info = ComponentInfo(
            jinjax_name="Badge",
            file_path=Path("/c/Badge.jinja"),
            rel_path="Badge.jinja",
            prefix="",
            import_path="Badge.jinja",
        )
        assert add_auto_assets(source, info, "/static/") == source

    def test_inserts_before_def(self):
        source = "{#def title #}\n<div>{{ title }}</div>\n"
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
            has_css=True,
            css_path=Path("/c/Card.css"),
        )
        result = add_auto_assets(source, info, "/static/")
        css_pos = result.index("{#css")
        def_pos = result.index("{#def")
        assert css_pos < def_pos

    def test_inserts_after_existing_asset_decl(self):
        source = "{#css existing.css #}\n{#def title #}\n"
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
            has_js=True,
            js_path=Path("/c/Card.js"),
        )
        result = add_auto_assets(source, info, "/static/")
        # JS should come after existing CSS
        lines = result.splitlines()
        css_line = next(i for i, line in enumerate(lines) if "existing.css" in line)
        js_line = next(i for i, line in enumerate(lines) if "Card.js" in line)
        assert js_line > css_line

    def test_prefixed_component_url(self):
        source = "{#def message #}\n"
        info = ComponentInfo(
            jinjax_name="ui:Alert",
            file_path=Path("/v/Alert.jinja"),
            rel_path="Alert.jinja",
            prefix="ui",
            import_path="@ui/Alert.jinja",
            has_css=True,
            css_path=Path("/v/Alert.css"),
        )
        result = add_auto_assets(source, info, "/static/")
        assert "{#css /static/ui/Alert.css #}" in result


class TestUpdateAssetPaths:
    def test_relative_path_gets_prefix(self):
        source = "{#css card.css #}\n"
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "{#css /static/card.css #}" in result

    def test_absolute_path_unchanged(self):
        source = "{#css /already/absolute.css #}\n"
        info = ComponentInfo(
            jinjax_name="X",
            file_path=Path("/c/X.jinja"),
            rel_path="X.jinja",
            prefix="",
            import_path="X.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "/already/absolute.css" in result

    def test_http_url_unchanged(self):
        source = "{#css https://cdn.example.com/style.css #}\n"
        result = update_asset_paths(source, None, "/static/")
        assert "https://cdn.example.com/style.css" in result

    def test_multiple_paths(self):
        source = '{#css card.css, https://cdn.com/lib.css #}\n'
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "/static/card.css" in result
        assert "https://cdn.com/lib.css" in result

    def test_js_paths_updated(self):
        source = "{#js script.js #}\n"
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "{#js /static/script.js #}" in result

    def test_prefixed_component(self):
        source = "{#css alert.css #}\n"
        info = ComponentInfo(
            jinjax_name="ui:Alert",
            file_path=Path("/v/Alert.jinja"),
            rel_path="Alert.jinja",
            prefix="ui",
            import_path="@ui/Alert.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "/static/ui/alert.css" in result

    def test_quoted_paths_stripped(self):
        source = '{#css "card.css" #}\n'
        info = ComponentInfo(
            jinjax_name="Card",
            file_path=Path("/c/Card.jinja"),
            rel_path="Card.jinja",
            prefix="",
            import_path="Card.jinja",
        )
        result = update_asset_paths(source, info, "/static/")
        assert "/static/card.css" in result

    def test_no_info_defaults_to_no_prefix(self):
        source = "{#css style.css #}\n"
        result = update_asset_paths(source, None, "/static/")
        assert "{#css /static/style.css #}" in result
