import pytest

from migrate import (
    CatalogFolder,
    ComponentRegistry,
)


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
def tmp_nested_kebab(tmp_path):
    """Create a component nested in kebab-case folders."""
    comp = tmp_path / "components-nested"
    nested = comp / "foo" / "lorem-ipsum"
    nested.mkdir(parents=True)
    (nested / "Bar.jinja").write_text(
        '{#def x #}\n<div class="bar">{{ x }}</div>\n'
    )
    return comp


@pytest.fixture
def registry(tmp_components, tmp_prefixed):
    """Build a ComponentRegistry from test fixtures."""
    reg = ComponentRegistry()
    reg.add_folder(CatalogFolder(path=tmp_components, prefix=""))
    reg.add_folder(CatalogFolder(path=tmp_prefixed, prefix="ui"))
    return reg


@pytest.fixture
def registry_with_nested(tmp_components, tmp_prefixed, tmp_nested_kebab):
    """Build a ComponentRegistry that includes nested kebab-case components."""
    reg = ComponentRegistry()
    reg.add_folder(CatalogFolder(path=tmp_components, prefix=""))
    reg.add_folder(CatalogFolder(path=tmp_prefixed, prefix="ui"))
    reg.add_folder(CatalogFolder(path=tmp_nested_kebab, prefix=""))
    return reg
