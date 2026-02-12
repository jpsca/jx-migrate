"""Unit tests for the JinjaX-to-Jx migration script."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from migrate import (
    CatalogFolder,
    ComponentInfo,
    ComponentRegistry,
    add_auto_assets,
    create_backup,
    execute_asset_copies,
    find_component_tags,
    find_slot_blocks,
    generate_imports_and_rename,
    get_asset_url,
    kebab_case,
    migrate_asset_rendering,
    migrate_slot_definitions,
    migrate_slot_usage,
    plan_asset_copies,
    protect_raw_blocks,
    restore_raw_blocks,
    to_pascal_case,
    transform_file,
    update_asset_paths,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def tmp_components(tmp_path):
    """Create a temporary component directory structure with assets."""
    comp = tmp_path / "components"
    comp.mkdir()

    # Simple component
    (comp / "Card.jinja").write_text(
        '{#def title #}\n<div class="card">{{ title }}</div>\n'
    )
    (comp / "Card.css").write_text(".card { border: 1px solid; }\n")

    # Component with explicit assets
    (comp / "Button.jinja").write_text(
        '{#def label #}\n{#css Button.css #}\n{#js Button.js #}\n'
        '<button>{{ label }}</button>\n'
    )
    (comp / "Button.css").write_text(".btn { cursor: pointer; }\n")
    (comp / "Button.js").write_text("console.log('btn');\n")

    # Subfolder component
    common = comp / "common"
    common.mkdir()
    (common / "Form.jinja").write_text(
        '{#def action #}\n<form action="{{ action }}">{{ content }}</form>\n'
    )

    # Component with no assets
    (comp / "Badge.jinja").write_text(
        '{#def text #}\n<span class="badge">{{ text }}</span>\n'
    )

    return comp


@pytest.fixture
def tmp_prefixed(tmp_path):
    """Create a prefixed component directory."""
    vendor = tmp_path / "vendor-ui"
    vendor.mkdir()
    (vendor / "Alert.jinja").write_text(
        '{#def message #}\n<div class="alert">{{ message }}</div>\n'
    )
    (vendor / "Alert.css").write_text(".alert { padding: 12px; }\n")
    return vendor


@pytest.fixture
def registry(tmp_components, tmp_prefixed):
    """Build a ComponentRegistry from test fixtures."""
    reg = ComponentRegistry()
    reg.add_folder(CatalogFolder(path=tmp_components, prefix=""))
    reg.add_folder(CatalogFolder(path=tmp_prefixed, prefix="ui"))
    return reg


# =========================================================================
# Utility functions
# =========================================================================


class TestToPascalCase:
    def test_simple(self):
        assert to_pascal_case("button") == "Button"

    def test_kebab(self):
        assert to_pascal_case("my-button") == "MyButton"

    def test_snake(self):
        assert to_pascal_case("my_button") == "MyButton"

    def test_already_pascal(self):
        assert to_pascal_case("Button") == "Button"

    def test_mixed_separators(self):
        assert to_pascal_case("my-cool_widget") == "MyCoolWidget"

    def test_single_char(self):
        assert to_pascal_case("a") == "A"


class TestKebabCase:
    def test_simple(self):
        assert kebab_case("Button") == "button"

    def test_multi_word(self):
        assert kebab_case("MyButton") == "my-button"

    def test_already_lower(self):
        assert kebab_case("button") == "button"


class TestRawBlockProtection:
    def test_protect_and_restore(self):
        source = 'before {% raw %}<Card />{% endraw %} after'
        protected, placeholders = protect_raw_blocks(source)
        assert "<Card />" not in protected
        assert len(placeholders) == 1
        restored = restore_raw_blocks(protected, placeholders)
        assert restored == source

    def test_multiple_raw_blocks(self):
        source = '{% raw %}A{% endraw %} middle {% raw %}B{% endraw %}'
        protected, placeholders = protect_raw_blocks(source)
        assert len(placeholders) == 2
        restored = restore_raw_blocks(protected, placeholders)
        assert restored == source

    def test_no_raw_blocks(self):
        source = "<Card />"
        protected, placeholders = protect_raw_blocks(source)
        assert protected == source
        assert len(placeholders) == 0

    def test_whitespace_variants(self):
        source = '{%- raw -%}<Card />{%- endraw -%}'
        protected, placeholders = protect_raw_blocks(source)
        assert "<Card />" not in protected
        restored = restore_raw_blocks(protected, placeholders)
        assert restored == source


# =========================================================================
# Phase 1: Component Registry
# =========================================================================


class TestComponentRegistry:
    def test_discovers_components(self, registry, tmp_components):
        names = set(registry.components.keys())
        assert "Card" in names
        assert "Button" in names
        assert "Badge" in names
        assert "common.Form" in names
        assert "ui:Alert" in names

    def test_component_count(self, registry):
        assert len(registry.components) == 5

    def test_simple_component_info(self, registry):
        info = registry.components["Card"]
        assert info.rel_path == "Card.jinja"
        assert info.prefix == ""
        assert info.import_path == "Card.jinja"
        assert info.has_css is True
        assert info.has_js is False

    def test_subfolder_component_info(self, registry):
        info = registry.components["common.Form"]
        assert info.rel_path == "common/Form.jinja"
        assert info.prefix == ""
        assert info.import_path == "common/Form.jinja"

    def test_prefixed_component_info(self, registry):
        info = registry.components["ui:Alert"]
        assert info.rel_path == "Alert.jinja"
        assert info.prefix == "ui"
        assert info.import_path == "@ui/Alert.jinja"
        assert info.has_css is True

    def test_component_with_css_and_js(self, registry):
        info = registry.components["Button"]
        assert info.has_css is True
        assert info.has_js is True
        assert info.css_path is not None
        assert info.js_path is not None

    def test_component_without_assets(self, registry):
        info = registry.components["Badge"]
        assert info.has_css is False
        assert info.has_js is False
        assert info.css_path is None
        assert info.js_path is None

    def test_resolve_direct(self, registry):
        info = registry.resolve("Card")
        assert info is not None
        assert info.jinjax_name == "Card"

    def test_resolve_subfolder(self, registry):
        info = registry.resolve("common.Form")
        assert info is not None
        assert info.jinjax_name == "common.Form"

    def test_resolve_prefixed(self, registry):
        info = registry.resolve("ui:Alert")
        assert info is not None
        assert info.jinjax_name == "ui:Alert"

    def test_resolve_case_insensitive(self, registry):
        info = registry.resolve("Common.Form")
        assert info is not None
        assert info.jinjax_name == "common.Form"

    def test_resolve_unknown(self, registry):
        assert registry.resolve("NonExistent") is None

    def test_get_alias_simple(self, registry):
        info = registry.components["Card"]
        assert registry.get_alias(info) == "Card"

    def test_get_alias_subfolder(self, registry):
        info = registry.components["common.Form"]
        assert registry.get_alias(info) == "Form"

    def test_get_alias_prefixed(self, registry):
        info = registry.components["ui:Alert"]
        assert registry.get_alias(info) == "Alert"

    def test_add_folder_returns_count(self, tmp_path):
        comp = tmp_path / "c"
        comp.mkdir()
        (comp / "A.jinja").write_text("")
        (comp / "B.jinja").write_text("")
        reg = ComponentRegistry()
        assert reg.add_folder(CatalogFolder(path=comp, prefix="")) == 2

    def test_index_convention(self, tmp_path):
        comp = tmp_path / "c"
        tab = comp / "tab"
        tab.mkdir(parents=True)
        (tab / "index.jinja").write_text("")
        reg = ComponentRegistry()
        reg.add_folder(CatalogFolder(path=comp, prefix=""))
        assert "Tab" in reg.components

    def test_kebab_filename(self, tmp_path):
        comp = tmp_path / "c"
        comp.mkdir()
        (comp / "my-button.jinja").write_text("")
        reg = ComponentRegistry()
        reg.add_folder(CatalogFolder(path=comp, prefix=""))
        assert "MyButton" in reg.components

    def test_no_duplicate_registration(self, tmp_path):
        comp = tmp_path / "c"
        comp.mkdir()
        (comp / "Card.jinja").write_text("")
        reg = ComponentRegistry()
        reg.add_folder(CatalogFolder(path=comp, prefix=""))
        reg.add_folder(CatalogFolder(path=comp, prefix=""))
        # Second add shouldn't increase count because name already registered
        assert len(reg.components) == 1


# =========================================================================
# Phase 2: Asset Migration
# =========================================================================


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


# =========================================================================
# Phase 3a: Slot Definition Migration
# =========================================================================


class TestMigrateSlotDefinitions:
    def test_named_slot(self):
        source = '{{ content("header") }}'
        assert migrate_slot_definitions(source) == "{% slot header %}{% endslot %}"

    def test_named_slot_single_quotes(self):
        source = "{{ content('footer') }}"
        assert migrate_slot_definitions(source) == "{% slot footer %}{% endslot %}"

    def test_multiple_named_slots(self):
        source = '{{ content("header") }}\n{{ content("footer") }}'
        result = migrate_slot_definitions(source)
        assert "{% slot header %}{% endslot %}" in result
        assert "{% slot footer %}{% endslot %}" in result

    def test_empty_call_becomes_variable(self):
        source = "{{ content() }}"
        assert migrate_slot_definitions(source) == "{{ content }}"

    def test_plain_content_unchanged(self):
        source = "{{ content }}"
        assert migrate_slot_definitions(source) == "{{ content }}"

    def test_content_in_conditional_unchanged(self):
        source = "{% if content %}has content{% endif %}"
        assert migrate_slot_definitions(source) == source

    def test_whitespace_variations(self):
        source = '{{  content( "header" )  }}'
        assert migrate_slot_definitions(source) == "{% slot header %}{% endslot %}"

    def test_mixed_content_types(self):
        source = (
            '<div>{{ content }}</div>\n'
            '<header>{{ content("header") }}</header>\n'
            '<footer>{{ content() }}</footer>\n'
        )
        result = migrate_slot_definitions(source)
        assert "{{ content }}" in result
        assert "{% slot header %}{% endslot %}" in result
        # content() becomes {{ content }}
        assert result.count("{{ content }}") == 2

    def test_surrounding_html_preserved(self):
        source = '<div class="header">{{ content("header") }}</div>'
        result = migrate_slot_definitions(source)
        assert result == '<div class="header">{% slot header %}{% endslot %}</div>'


# =========================================================================
# Phase 3b: Slot Usage Migration
# =========================================================================


class TestFindSlotBlocks:
    def test_simple_if_else(self):
        source = '{% if _slot == "header" %}H{% else %}D{% endif %}'
        blocks = find_slot_blocks(source)
        assert len(blocks) == 1
        assert len(blocks[0].branches) == 1
        assert blocks[0].branches[0].name == "header"
        assert blocks[0].branches[0].body == "H"
        assert blocks[0].default_body == "D"

    def test_if_elif(self):
        source = (
            '{% if _slot == "header" %}H'
            '{% elif _slot == "footer" %}F'
            '{% endif %}'
        )
        blocks = find_slot_blocks(source)
        assert len(blocks) == 1
        assert len(blocks[0].branches) == 2
        assert blocks[0].branches[0].name == "header"
        assert blocks[0].branches[1].name == "footer"

    def test_if_elif_else(self):
        source = (
            '{% if _slot == "header" %}H'
            '{% elif _slot == "footer" %}F'
            '{% else %}D'
            '{% endif %}'
        )
        blocks = find_slot_blocks(source)
        assert len(blocks) == 1
        assert len(blocks[0].branches) == 2
        assert blocks[0].default_body == "D"

    def test_mixed_conditional_skipped(self):
        source = (
            '{% if _slot == "header" %}H'
            '{% elif some_other_var %}X'
            '{% endif %}'
        )
        blocks = find_slot_blocks(source)
        assert len(blocks) == 0

    def test_nested_if_inside_slot(self):
        source = (
            '{% if _slot == "header" %}'
            '{% if user %}{{ user.name }}{% endif %}'
            '{% else %}Default{% endif %}'
        )
        blocks = find_slot_blocks(source)
        assert len(blocks) == 1
        assert "{% if user %}" in blocks[0].branches[0].body

    def test_no_slot_blocks(self):
        source = "{% if show %}visible{% endif %}"
        blocks = find_slot_blocks(source)
        assert len(blocks) == 0

    def test_whitespace_trimming_variants(self):
        source = '{%- if _slot == "header" -%}H{%- endif -%}'
        blocks = find_slot_blocks(source)
        assert len(blocks) == 1


class TestMigrateSlotUsage:
    def test_simple_if_else(self):
        source = '{% if _slot == "header" %}H{% else %}D{% endif %}'
        result, warnings = migrate_slot_usage(source)
        assert "{% fill header %}" in result
        assert "{% endfill %}" in result
        assert "D" in result
        assert "_slot" not in result

    def test_multiple_branches(self):
        source = (
            '    {% if _slot == "header" %}\n'
            '      <h1>Title</h1>\n'
            '    {% elif _slot == "footer" %}\n'
            '      <p>Footer</p>\n'
            '    {% else %}\n'
            '      Default\n'
            '    {% endif %}'
        )
        result, warnings = migrate_slot_usage(source)
        assert "{% fill header %}" in result
        assert "{% fill footer %}" in result
        assert "{% endfill %}" in result
        assert "_slot" not in result
        assert "Default" in result

    def test_indentation_preserved(self):
        source = '    {% if _slot == "header" %}H{% endif %}'
        result, _ = migrate_slot_usage(source)
        assert result.startswith("    {% fill header %}")

    def test_no_slots_returns_unchanged(self):
        source = "<div>Hello</div>"
        result, warnings = migrate_slot_usage(source)
        assert result == source
        assert warnings == []

    def test_only_default_body_when_has_content(self):
        source = '{% if _slot == "x" %}X{% else %}{% endif %}'
        result, _ = migrate_slot_usage(source)
        # Empty default body should not appear
        assert result == "{% fill x %}X{% endfill %}"

    def test_multiple_slot_blocks(self):
        source = (
            'A{% if _slot == "a" %}A-content{% endif %}B'
            '{% if _slot == "b" %}B-content{% endif %}C'
        )
        result, _ = migrate_slot_usage(source)
        assert "{% fill a %}" in result
        assert "{% fill b %}" in result


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
        css_line = next(i for i, l in enumerate(lines) if "existing.css" in l)
        js_line = next(i for i, l in enumerate(lines) if "Card.js" in l)
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


# =========================================================================
# Phase 3f: Import Generation and Tag Renaming
# =========================================================================


class TestFindComponentTags:
    def test_opening_tag(self):
        tags = find_component_tags("<Card>content</Card>")
        assert "Card" in tags

    def test_self_closing_tag(self):
        tags = find_component_tags('<Button label="x" />')
        assert "Button" in tags

    def test_dotted_tag(self):
        tags = find_component_tags("<common.Form>")
        assert "common.Form" in tags

    def test_prefixed_tag(self):
        tags = find_component_tags("<ui:Alert />")
        assert "ui:Alert" in tags

    def test_multiple_tags(self):
        tags = find_component_tags("<Card><Button /></Card>")
        assert "Card" in tags
        assert "Button" in tags

    def test_html_tags_excluded(self):
        tags = find_component_tags("<div><span>text</span></div>")
        assert len(tags) == 0

    def test_closing_tags_included(self):
        tags = find_component_tags("</Card>")
        assert "Card" in tags

    def test_deduplicates(self):
        tags = find_component_tags("<Card><Card /></Card>")
        assert tags == {"Card"}


class TestGenerateImportsAndRename:
    def test_simple_import(self, registry, tmp_path):
        source = "<Card>content</Card>"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "Card.jinja" as Card #}' in result

    def test_subfolder_import_and_rename(self, registry, tmp_path):
        source = '<common.Form action="/">\ncontent\n</common.Form>'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "common/Form.jinja" as Form #}' in result
        assert "<Form " in result
        assert "</Form>" in result
        assert "common.Form" not in result

    def test_prefixed_import_and_rename(self, registry, tmp_path):
        source = '<ui:Alert message="hi" />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "@ui/Alert.jinja" as Alert #}' in result
        assert "<Alert " in result
        assert "ui:Alert" not in result

    def test_unknown_tags_ignored(self, registry, tmp_path):
        source = "<UnknownWidget />"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert "import" not in result
        assert "<UnknownWidget />" in result

    def test_multiple_imports(self, registry, tmp_path):
        source = "<Card><Button /></Card>"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "Button.jinja" as Button #}' in result
        assert '{#import "Card.jinja" as Card #}' in result

    def test_idempotent_existing_import(self, registry, tmp_path):
        source = '{#import "Card.jinja" as Card #}\n<Card />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert result.count('{#import "Card.jinja" as Card #}') == 1

    def test_raw_blocks_protected(self, registry, tmp_path):
        source = '{% raw %}<Card />{% endraw %}\n<Button />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        # Card inside raw should not be imported
        assert "Card.jinja" not in result
        # Button outside raw should be imported
        assert '{#import "Button.jinja" as Button #}' in result
        # Raw block content should be preserved
        assert "{% raw %}<Card />{% endraw %}" in result

    def test_imports_before_def(self, registry, tmp_path):
        source = '{#def title #}\n<Card />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        import_pos = result.index("{#import")
        def_pos = result.index("{#def")
        assert import_pos < def_pos

    def test_imports_after_existing_imports(self, registry, tmp_path):
        source = '{#import "Badge.jinja" as Badge #}\n{#def x #}\n<Card />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        lines = result.splitlines()
        badge_line = next(i for i, l in enumerate(lines) if "Badge" in l)
        card_line = next(i for i, l in enumerate(lines) if "Card" in l)
        assert card_line > badge_line


# =========================================================================
# Full Pipeline: transform_file
# =========================================================================


class TestTransformFile:
    def test_slot_definitions_migrated(self, tmp_components, registry):
        comp = tmp_components / "SlotComp.jinja"
        comp.write_text(
            '{#def title #}\n'
            '<div>{{ content("header") }}</div>\n'
            '<div>{{ content }}</div>\n'
        )
        # Re-register
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(comp, registry, "/static/")
        assert "{% slot header %}{% endslot %}" in changes.transformed
        assert "{{ content }}" in changes.transformed
        assert changes.changed

    def test_slot_usage_migrated(self, tmp_components, registry):
        page = tmp_components / "UsePage.jinja"
        page.write_text(
            '<Card>\n'
            '{% if _slot == "header" %}H{% else %}D{% endif %}\n'
            '</Card>\n'
        )
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(page, registry, "/static/")
        assert "{% fill header %}" in changes.transformed
        assert "_slot" not in changes.transformed

    def test_catalog_render_assets_migrated(self, tmp_components, registry):
        page = tmp_components / "Layout.jinja"
        page.write_text(
            '<head>{{ catalog.render_assets() }}</head>\n'
        )
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(page, registry, "/static/")
        assert "{{ assets.render() }}" in changes.transformed
        assert "catalog.render_assets" not in changes.transformed

    def test_auto_assets_added(self, tmp_components, registry):
        # Card.jinja has Card.css but no {#css#} declaration
        card = tmp_components / "Card.jinja"
        changes = transform_file(card, registry, "/static/")
        assert "{#css /static/Card.css #}" in changes.transformed

    def test_asset_paths_updated(self, tmp_components, registry):
        # Button.jinja has {#css Button.css #}
        button = tmp_components / "Button.jinja"
        changes = transform_file(button, registry, "/static/")
        assert "{#css /static/Button.css #}" in changes.transformed
        assert "{#js /static/Button.js #}" in changes.transformed

    def test_imports_generated(self, tmp_components, registry):
        page = tmp_components / "TestPage.jinja"
        page.write_text("<Card /><Button />")
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(page, registry, "/static/")
        assert '{#import "Card.jinja" as Card #}' in changes.transformed
        assert '{#import "Button.jinja" as Button #}' in changes.transformed

    def test_unchanged_file(self, tmp_components, registry):
        page = tmp_components / "Plain.jinja"
        page.write_text("<div>No components here</div>\n")
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(page, registry, "/static/")
        assert not changes.changed

    def test_all_transformations_combined(self, tmp_components, tmp_prefixed, registry):
        page = tmp_components / "FullPage.jinja"
        page.write_text(
            '{#def title #}\n'
            '<head>{{ catalog.render_assets() }}</head>\n'
            '<Card title="{{ title }}">\n'
            '{% if _slot == "header" %}<h1>{{ title }}</h1>\n'
            '{% else %}Default{% endif %}\n'
            '</Card>\n'
            '<ui:Alert message="hi" />\n'
        )
        registry.add_folder(CatalogFolder(path=tmp_components, prefix=""))
        changes = transform_file(page, registry, "/static/")
        t = changes.transformed
        # Imports
        assert '{#import "Card.jinja" as Card #}' in t
        assert '{#import "@ui/Alert.jinja" as Alert #}' in t
        # Asset rendering
        assert "{{ assets.render() }}" in t
        # Slots
        assert "{% fill header %}" in t
        assert "_slot" not in t
        # Tag renames
        assert "<Alert " in t
        assert "ui:Alert" not in t


# =========================================================================
# Backup
# =========================================================================


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
