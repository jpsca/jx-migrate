from migrate import (
    find_slot_blocks,
    migrate_slot_definitions,
    migrate_slot_usage,
)


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
