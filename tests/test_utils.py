from migrate import (
    to_pascal_case,
    kebab_case,
    protect_raw_blocks,
    restore_raw_blocks,
)


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
