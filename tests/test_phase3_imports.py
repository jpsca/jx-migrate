
from migrate import (
    find_component_tags,
    generate_imports_and_rename,
)


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
        assert '{#import "Card.jx" as Card #}' in result

    def test_subfolder_import_and_rename(self, registry, tmp_path):
        source = '<common.Form action="/">\ncontent\n</common.Form>'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "common/Form.jx" as Form #}' in result
        assert "<Form " in result
        assert "</Form>" in result
        assert "common.Form" not in result

    def test_prefixed_import_and_rename(self, registry, tmp_path):
        source = '<ui:Alert message="hi" />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert '{#import "@ui/Alert.jx" as Alert #}' in result
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
        assert '{#import "Button.jx" as Button #}' in result
        assert '{#import "Card.jx" as Card #}' in result

    def test_idempotent_existing_import(self, registry, tmp_path):
        source = '{#import "Card.jx" as Card #}\n<Card />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        assert result.count('{#import "Card.jx" as Card #}') == 1

    def test_raw_blocks_protected(self, registry, tmp_path):
        source = "{% raw %}<Card />{% endraw %}\n<Button />"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        # Card inside raw should not be imported
        assert "Card.jx" not in result
        # Button outside raw should be imported
        assert '{#import "Button.jx" as Button #}' in result
        # Raw block content should be preserved
        assert "{% raw %}<Card />{% endraw %}" in result

    def test_imports_before_def(self, registry, tmp_path):
        source = "{#def title #}\n<Card />"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        import_pos = result.index("{#import")
        def_pos = result.index("{#def")
        assert import_pos < def_pos

    def test_imports_after_existing_imports(self, registry, tmp_path):
        source = '{#import "Badge.jx" as Badge #}\n{#def x #}\n<Card />'
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry
        )
        lines = result.splitlines()
        badge_line = next(i for i, line in enumerate(lines) if "Badge" in line)
        card_line = next(i for i, line in enumerate(lines) if "Card" in line)
        assert card_line > badge_line


class TestNestedKebabCaseComponents:
    """Test migration of components nested in kebab-case folders.

    A component at foo/lorem-ipsum/Bar.jinja can be referenced in templates
    using either kebab-case path segments (foo.lorem-ipsum.Bar) or PascalCase
    path segments (Foo.LoremIpsum.Bar). Both forms should resolve and migrate.
    """

    def test_find_tags_kebab_case_path(self):
        tags = find_component_tags(
            "<foo.lorem-ipsum.Bar>hello</foo.lorem-ipsum.Bar>"
        )
        assert "foo.lorem-ipsum.Bar" in tags

    def test_find_tags_kebab_case_self_closing(self):
        tags = find_component_tags("<foo.lorem-ipsum.Bar />")
        assert "foo.lorem-ipsum.Bar" in tags

    def test_find_tags_pascal_case_path(self):
        tags = find_component_tags(
            "<Foo.LoremIpsum.Bar>hello</Foo.LoremIpsum.Bar>"
        )
        assert "Foo.LoremIpsum.Bar" in tags

    def test_find_tags_pascal_case_self_closing(self):
        tags = find_component_tags("<Foo.LoremIpsum.Bar />")
        assert "Foo.LoremIpsum.Bar" in tags

    def test_kebab_case_opening_closing(self, registry_with_nested, tmp_path):
        source = "<foo.lorem-ipsum.Bar>hello</foo.lorem-ipsum.Bar>"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry_with_nested
        )
        assert '{#import "foo/lorem-ipsum/Bar.jx" as Bar #}' in result
        assert "<Bar>" in result
        assert "</Bar>" in result
        assert "foo.lorem-ipsum.Bar" not in result

    def test_kebab_case_self_closing(self, registry_with_nested, tmp_path):
        source = "<foo.lorem-ipsum.Bar />"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry_with_nested
        )
        assert '{#import "foo/lorem-ipsum/Bar.jx" as Bar #}' in result
        assert "<Bar />" in result
        assert "foo.lorem-ipsum.Bar" not in result

    def test_pascal_case_opening_closing(self, registry_with_nested, tmp_path):
        source = "<Foo.LoremIpsum.Bar>hello</Foo.LoremIpsum.Bar>"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry_with_nested
        )
        assert '{#import "foo/lorem-ipsum/Bar.jx" as Bar #}' in result
        assert "<Bar>" in result
        assert "</Bar>" in result
        assert "Foo.LoremIpsum.Bar" not in result

    def test_pascal_case_self_closing(self, registry_with_nested, tmp_path):
        source = "<Foo.LoremIpsum.Bar />"
        result, warnings = generate_imports_and_rename(
            source, tmp_path / "Page.jinja", registry_with_nested
        )
        assert '{#import "foo/lorem-ipsum/Bar.jx" as Bar #}' in result
        assert "<Bar />" in result
        assert "Foo.LoremIpsum.Bar" not in result
