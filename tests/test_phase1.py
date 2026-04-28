from migrate import (
    CatalogFolder,
    ComponentRegistry,
)


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
        assert info.import_path == "Card.jx"
        assert info.has_css is True
        assert info.has_js is False

    def test_subfolder_component_info(self, registry):
        info = registry.components["common.Form"]
        assert info.rel_path == "common/Form.jinja"
        assert info.prefix == ""
        assert info.import_path == "common/Form.jx"

    def test_prefixed_component_info(self, registry):
        info = registry.components["ui:Alert"]
        assert info.rel_path == "Alert.jinja"
        assert info.prefix == "ui"
        assert info.import_path == "@ui/Alert.jx"
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