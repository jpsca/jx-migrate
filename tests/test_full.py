from migrate import (
    CatalogFolder,
    transform_file,
)


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
        assert '{#import "Card.jx" as Card #}' in changes.transformed
        assert '{#import "Button.jx" as Button #}' in changes.transformed

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
        assert '{#import "Card.jx" as Card #}' in t
        assert '{#import "@ui/Alert.jx" as Alert #}' in t
        # Asset rendering
        assert "{{ assets.render() }}" in t
        # Slots
        assert "{% fill header %}" in t
        assert "_slot" not in t
        # Tag renames
        assert "<Alert " in t
        assert "ui:Alert" not in t

