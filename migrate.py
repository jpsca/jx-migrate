#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""JinjaX to Jx migration script.

Migrates .jinja component templates from JinjaX syntax to Jx syntax:
- Generates explicit {#import ...#} statements
- Migrates slot syntax (content("name") -> {% slot %}, _slot conditionals -> {% fill %})
- Moves co-located CSS/JS assets to a static folder
- Updates asset declarations and rendering calls

Usage:
    uv run migrate.py [--dry-run] [--no-backup]
"""

from __future__ import annotations

import argparse
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Regex patterns (adapted from JinjaX and Jx source)
# ---------------------------------------------------------------------------

re_tag_prefix = r"([0-9A-Za-z\._-]+\:)?"
re_tag_path = r"([0-9A-Za-z_-]+\.)*[A-Z][0-9A-Za-z_-]*"
re_tag_name = rf"{re_tag_prefix}{re_tag_path}"

# Matches opening component tags: <Card, <ui:Button, <common.Form
RX_OPEN_TAG = re.compile(rf"<(?P<tag>{re_tag_name})(?P<after>\s|\n|/|>)")
# Matches closing component tags: </Card>, </ui:Button>
RX_CLOSE_TAG = re.compile(rf"</(?P<tag>{re_tag_name})\s*>")

# Raw block protection
RX_RAW = re.compile(r"\{%-?\s*raw\s*-?%\}.+?\{%-?\s*endraw\s*-?%\}", re.DOTALL)

# Metadata declarations
RX_META_HEADER = re.compile(r"^(\s*\{#.*?#\})+", re.DOTALL)
RX_DEF_START = re.compile(r"\{#-?\s*def\s+")
RX_CSS_DECL = re.compile(r"\{#-?\s*css\s+(.*?)\s*-?#\}", re.DOTALL)
RX_JS_DECL = re.compile(r"\{#-?\s*js\s+(.*?)\s*-?#\}", re.DOTALL)
RX_EXISTING_IMPORT = re.compile(r"\{#-?\s*import\s+\"([^\"]+)\"\s+as\s+(\w+)\s*#\}")

# Slot definitions: {{ content("name") }} and {{ content() }}
RX_CONTENT_NAMED = re.compile(r"\{\{\s*content\(\s*[\"'](\w+)[\"']\s*\)\s*\}\}")
RX_CONTENT_EMPTY_CALL = re.compile(r"\{\{\s*content\(\s*\)\s*\}\}")

# Slot usage: _slot conditionals
RX_SLOT_IF = re.compile(r"\{%-?\s*if\s+_slot\s*==\s*[\"'](\w+)[\"']\s*-?%\}")
RX_SLOT_ELIF = re.compile(r"\{%-?\s*elif\s+_slot\s*==\s*[\"'](\w+)[\"']\s*-?%\}")
RX_ELIF_OTHER = re.compile(r"\{%-?\s*elif\s+")
RX_ELSE = re.compile(r"\{%-?\s*else\s*-?%\}")
RX_ENDIF = re.compile(r"\{%-?\s*endif\s*-?%\}")
RX_IF_OPEN = re.compile(r"\{%-?\s*if\s+")

# Asset rendering
RX_CATALOG_RENDER_ASSETS = re.compile(
    r"\{\{\s*catalog\.render_assets\(\)\s*\}\}"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CatalogFolder:
    path: Path
    prefix: str  # "" for no prefix


@dataclass
class ComponentInfo:
    jinjax_name: str       # e.g. "Card", "common.Form", "ui:Button"
    file_path: Path        # absolute path to .jinja file
    rel_path: str          # relative path from catalog root, e.g. "common/Form.jinja"
    prefix: str            # "" or "ui"
    import_path: str       # Jx import path: "common/form.jinja" or "@ui/button.jinja"
    has_css: bool = False
    has_js: bool = False
    css_path: Path | None = None
    js_path: Path | None = None


@dataclass
class SlotBranch:
    name: str  # slot name
    body: str  # content body


@dataclass
class SlotBlock:
    start: int
    end: int
    branches: list[SlotBranch]
    default_body: str  # content from {% else %} branch


@dataclass
class FileChanges:
    file_path: Path
    original: str
    transformed: str
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.original != self.transformed


@dataclass
class MigrationResult:
    file_changes: list[FileChanges] = field(default_factory=list)
    asset_copies: list[tuple[Path, Path]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def to_pascal_case(name: str) -> str:
    """Convert a kebab-case or snake_case name to PascalCase."""
    parts = re.split(r"[-_]", name)
    return "".join(p.capitalize() for p in parts if p)


def kebab_case(name: str) -> str:
    """Convert PascalCase to kebab-case."""
    s = re.sub(r"([A-Z])", r"-\1", name).lower().strip("-")
    return re.sub(r"-+", "-", s)


def protect_raw_blocks(source: str) -> tuple[str, dict[str, str]]:
    """Replace {% raw %}...{% endraw %} blocks with UUID placeholders."""
    placeholders: dict[str, str] = {}
    def replacer(m: re.Match) -> str:
        uid = f"__RAW_{uuid.uuid4().hex}__"
        placeholders[uid] = m.group(0)
        return uid
    return RX_RAW.sub(replacer, source), placeholders


def restore_raw_blocks(source: str, placeholders: dict[str, str]) -> str:
    """Restore raw blocks from placeholders."""
    for uid, original in placeholders.items():
        source = source.replace(uid, original)
    return source


# ---------------------------------------------------------------------------
# Phase 1: Component Registry
# ---------------------------------------------------------------------------


class ComponentRegistry:
    def __init__(self) -> None:
        self.components: dict[str, ComponentInfo] = {}  # keyed by jinjax_name
        self._folders: list[CatalogFolder] = []

    def add_folder(self, folder: CatalogFolder) -> int:
        """Scan a folder and register all components. Returns count."""
        self._folders.append(folder)
        count = 0
        root = folder.path.resolve()
        for jinja_file in sorted(root.rglob("*.jinja")):
            rel = jinja_file.relative_to(root)
            info = self._make_component_info(jinja_file, rel, root, folder.prefix)
            if info.jinjax_name not in self.components:
                self.components[info.jinjax_name] = info
                count += 1
        return count

    def _make_component_info(
        self, file_path: Path, rel: Path, root: Path, prefix: str
    ) -> ComponentInfo:
        parts = list(rel.parts)
        stem = rel.stem
        # Build JinjaX name: directory parts keep original case, stem is PascalCased
        # e.g. common/Form.jinja -> common.Form
        # e.g. common/my-button.jinja -> common.MyButton
        # e.g. tab/index.jinja -> Tab (index convention)
        if stem.lower() == "index" and len(parts) > 1:
            name_parts = list(parts[:-1])
            # Last dir part becomes the component name (PascalCased)
            name_parts[-1] = to_pascal_case(name_parts[-1])
        else:
            name_parts = list(parts[:-1]) + [to_pascal_case(stem)]
        jinjax_name = ".".join(name_parts)
        if prefix:
            jinjax_name = f"{prefix}:{jinjax_name}"

        # Build Jx import path
        rel_str = str(rel).replace("\\", "/")
        if prefix:
            import_path = f"@{prefix}/{rel_str}"
        else:
            import_path = rel_str

        # Check for co-located assets
        css_path = file_path.with_suffix(".css")
        js_path = file_path.with_suffix(".js")
        has_css = css_path.exists()
        has_js = js_path.exists()

        return ComponentInfo(
            jinjax_name=jinjax_name,
            file_path=file_path,
            rel_path=rel_str,
            prefix=prefix,
            import_path=import_path,
            has_css=has_css,
            has_js=has_js,
            css_path=css_path if has_css else None,
            js_path=js_path if has_js else None,
        )

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a component name for fuzzy matching.

        Strips hyphens/underscores and lowercases so that PascalCase path
        segments match their kebab-case or snake_case folder equivalents.
        e.g. "Foo.LoremIpsum.Bar" and "foo.lorem-ipsum.Bar" both become
        "foo.loremipsum.bar".
        """
        return name.replace("-", "").replace("_", "").lower()

    def resolve(self, tag_name: str) -> ComponentInfo | None:
        """Resolve a JinjaX tag name to a ComponentInfo."""
        # Direct lookup
        if tag_name in self.components:
            return self.components[tag_name]
        # Case-insensitive fallback (directory parts may differ in case)
        tag_lower = tag_name.lower()
        for name, info in self.components.items():
            if name.lower() == tag_lower:
                return info
        # Normalized fallback: strips hyphens/underscores so PascalCase path
        # segments match kebab-case folder names
        tag_norm = self._normalize(tag_name)
        for name, info in self.components.items():
            if self._normalize(name) == tag_norm:
                return info
        return None

    def get_alias(self, info: ComponentInfo) -> str:
        """Determine the import alias for a component."""
        # Use the last segment of the JinjaX name
        name = info.jinjax_name
        # Strip prefix
        if ":" in name:
            name = name.split(":", 1)[1]
        # Use last dot segment
        if "." in name:
            name = name.rsplit(".", 1)[1]
        return to_pascal_case(name)


# ---------------------------------------------------------------------------
# Phase 2: Asset Migration
# ---------------------------------------------------------------------------


def plan_asset_copies(
    registry: ComponentRegistry,
    static_folder: Path,
    url_prefix: str,
) -> list[tuple[Path, Path]]:
    """Plan asset file copies. Returns list of (source, destination) pairs."""
    copies: list[tuple[Path, Path]] = []
    seen_dests: set[Path] = set()

    # Normalize url_prefix to a relative directory under static_folder
    # e.g. "/static/components/" -> we want to put files under static_folder/
    # The url_prefix is for URLs; the static folder IS the filesystem root.

    for info in registry.components.values():
        for asset_path, suffix in [(info.css_path, ".css"), (info.js_path, ".js")]:
            if asset_path is None:
                continue
            # Build destination path preserving structure
            if info.prefix:
                dest = static_folder / info.prefix / Path(info.rel_path).with_suffix(suffix)
            else:
                dest = static_folder / Path(info.rel_path).with_suffix(suffix)
            if dest not in seen_dests:
                copies.append((asset_path, dest))
                seen_dests.add(dest)

    return copies


def execute_asset_copies(copies: list[tuple[Path, Path]], dry_run: bool) -> None:
    """Copy asset files to static folder."""
    for src, dest in copies:
        if dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


# ---------------------------------------------------------------------------
# Phase 3a: Slot definition migration
# ---------------------------------------------------------------------------


def migrate_slot_definitions(source: str) -> str:
    """Replace {{ content("name") }} with {% slot name %}{% endslot %}
    and {{ content() }} with {{ content }}."""
    # Named slots
    source = RX_CONTENT_NAMED.sub(r"{% slot \1 %}{% endslot %}", source)
    # Empty call -> plain variable
    source = RX_CONTENT_EMPTY_CALL.sub("{{ content }}", source)
    return source


# ---------------------------------------------------------------------------
# Phase 3b: Slot usage migration (stateful parser)
# ---------------------------------------------------------------------------


def find_slot_blocks(source: str) -> list[SlotBlock]:
    """Find all {% if _slot == "..." %} conditional blocks and parse them."""
    blocks: list[SlotBlock] = []

    # Find all potential _slot if-blocks
    for m in RX_SLOT_IF.finditer(source):
        start = m.start()
        first_name = m.group(1)
        pos = m.end()

        branches: list[SlotBranch] = []
        default_body = ""
        depth = 1
        current_name: str | None = first_name
        current_start = pos
        is_pure_slot = True  # all branches use _slot == "..."
        end = -1

        while depth > 0 and pos < len(source):
            # Find the next relevant Jinja tag
            next_matches = []
            for rx, label in [
                (RX_IF_OPEN, "if"),
                (RX_SLOT_ELIF, "slot_elif"),
                (RX_ELIF_OTHER, "elif_other"),
                (RX_ELSE, "else"),
                (RX_ENDIF, "endif"),
            ]:
                found = rx.search(source, pos)
                if found:
                    next_matches.append((found.start(), found, label))

            if not next_matches:
                break

            next_matches.sort(key=lambda x: x[0])
            _, tag_match, tag_type = next_matches[0]

            if tag_type == "if":
                depth += 1
                pos = tag_match.end()
            elif tag_type == "endif":
                depth -= 1
                if depth == 0:
                    body = source[current_start:tag_match.start()]
                    if current_name is not None:
                        branches.append(SlotBranch(current_name, body))
                    else:
                        default_body = body
                    end = tag_match.end()
                pos = tag_match.end()
            elif depth == 1 and tag_type == "slot_elif":
                body = source[current_start:tag_match.start()]
                if current_name is not None:
                    branches.append(SlotBranch(current_name, body))
                current_name = tag_match.group(1)
                current_start = tag_match.end()
                pos = tag_match.end()
            elif depth == 1 and tag_type == "elif_other":
                # Not a _slot elif -- mixed conditional, can't migrate safely
                is_pure_slot = False
                pos = tag_match.end()
                # Skip the rest of this block
                break
            elif depth == 1 and tag_type == "else":
                body = source[current_start:tag_match.start()]
                if current_name is not None:
                    branches.append(SlotBranch(current_name, body))
                current_name = None
                current_start = tag_match.end()
                pos = tag_match.end()
            else:
                pos = tag_match.end()

        if is_pure_slot and end > start and branches:
            blocks.append(SlotBlock(start, end, branches, default_body))

    return blocks


def migrate_slot_usage(source: str) -> tuple[str, list[str]]:
    """Replace _slot conditionals with {% fill %} blocks.
    Returns (transformed_source, warnings)."""
    warnings: list[str] = []
    blocks = find_slot_blocks(source)

    if not blocks:
        return source, warnings

    # Apply replacements in reverse order to preserve offsets
    for block in reversed(blocks):
        # Detect indentation of the original {% if _slot %} tag
        line_start = source.rfind("\n", 0, block.start) + 1
        indent = source[line_start:block.start]
        if not indent.isspace():
            indent = ""

        parts: list[str] = []
        for branch in block.branches:
            body = branch.body
            parts.append(f"{{% fill {branch.name} %}}{body}{{% endfill %}}")
        if block.default_body.strip():
            parts.append(block.default_body)
        replacement = ("\n" + indent).join(parts)
        source = source[:block.start] + replacement + source[block.end:]

    return source, warnings


# ---------------------------------------------------------------------------
# Phase 3c: Asset rendering calls
# ---------------------------------------------------------------------------


def migrate_asset_rendering(source: str) -> str:
    """Replace {{ catalog.render_assets() }} with {{ assets.render() }}."""
    return RX_CATALOG_RENDER_ASSETS.sub("{{ assets.render() }}", source)


# ---------------------------------------------------------------------------
# Phase 3d & 3e: Asset declarations
# ---------------------------------------------------------------------------


def get_asset_url(
    rel_path: str,
    prefix: str,
    url_prefix: str,
) -> str:
    """Build the static URL for a co-located asset."""
    if prefix:
        return f"{url_prefix}{prefix}/{rel_path}"
    return f"{url_prefix}{rel_path}"


def add_auto_assets(
    source: str,
    component_info: ComponentInfo | None,
    url_prefix: str,
) -> str:
    """Add {#css#}/{#js#} declarations for auto-discovered assets
    that aren't already declared."""
    if component_info is None:
        return source

    lines_to_add: list[str] = []

    if component_info.has_css:
        css_rel = str(Path(component_info.rel_path).with_suffix(".css")).replace("\\", "/")
        css_url = get_asset_url(css_rel, component_info.prefix, url_prefix)
        # Check if already declared
        if css_url not in source and css_rel not in source:
            stem_css = Path(component_info.rel_path).stem + ".css"
            if stem_css not in source:
                lines_to_add.append(f"{{#css {css_url} #}}")

    if component_info.has_js:
        js_rel = str(Path(component_info.rel_path).with_suffix(".js")).replace("\\", "/")
        js_url = get_asset_url(js_rel, component_info.prefix, url_prefix)
        if js_url not in source and js_rel not in source:
            stem_js = Path(component_info.rel_path).stem + ".js"
            if stem_js not in source:
                lines_to_add.append(f"{{#js {js_url} #}}")

    if not lines_to_add:
        return source

    # Insert after existing {#css#}/{#js#} or before {#def#} or at top
    insert_text = "\n".join(lines_to_add) + "\n"
    def_match = RX_DEF_START.search(source)
    css_matches = list(RX_CSS_DECL.finditer(source))
    js_matches = list(RX_JS_DECL.finditer(source))

    # Find the last existing asset declaration
    last_asset_end = 0
    for m in css_matches + js_matches:
        if m.end() > last_asset_end:
            last_asset_end = m.end()

    if last_asset_end > 0:
        # Insert after last asset declaration
        # Find end of line
        nl = source.find("\n", last_asset_end)
        if nl == -1:
            nl = last_asset_end
        insert_pos = nl + 1
    elif def_match:
        insert_pos = def_match.start()
    else:
        # Insert at top (after any existing imports)
        import_matches = list(RX_EXISTING_IMPORT.finditer(source))
        if import_matches:
            last_import = import_matches[-1]
            nl = source.find("\n", last_import.end())
            insert_pos = (nl + 1) if nl != -1 else last_import.end()
        else:
            insert_pos = 0

    return source[:insert_pos] + insert_text + source[insert_pos:]


def update_asset_paths(
    source: str,
    component_info: ComponentInfo | None,
    url_prefix: str,
) -> str:
    """Update relative paths in {#css ...#} and {#js ...#} to use static URL prefix."""
    prefix = component_info.prefix if component_info else ""

    def update_decl(m: re.Match) -> str:
        full = m.group(0)
        paths_str = m.group(1)
        is_css = full.lstrip().startswith("{#") and "css" in full[:20]
        tag = "css" if is_css else "js"

        paths = [p.strip().strip("\"'") for p in paths_str.split(",")]
        updated: list[str] = []
        for p in paths:
            if not p:
                continue
            if p.startswith(("http://", "https://", "/")):
                updated.append(p)
            else:
                updated.append(get_asset_url(p, prefix, url_prefix))
        return f"{{#{tag} {', '.join(updated)} #}}"

    source = RX_CSS_DECL.sub(update_decl, source)
    source = RX_JS_DECL.sub(update_decl, source)
    return source


# ---------------------------------------------------------------------------
# Phase 3f: Import generation and tag renaming
# ---------------------------------------------------------------------------


def find_component_tags(source: str) -> set[str]:
    """Find all PascalCase component tag names used in the source."""
    tags: set[str] = set()
    for m in RX_OPEN_TAG.finditer(source):
        tags.add(m.group("tag"))
    for m in RX_CLOSE_TAG.finditer(source):
        tags.add(m.group("tag"))
    return tags


def generate_imports_and_rename(
    source: str,
    file_path: Path,
    registry: ComponentRegistry,
) -> tuple[str, list[str]]:
    """Generate {#import ...#} statements and rename dotted/prefixed tags.
    Returns (transformed_source, warnings)."""
    warnings: list[str] = []

    # Protect raw blocks
    source, raw_placeholders = protect_raw_blocks(source)

    # Find existing imports to avoid duplicates
    existing_imports: dict[str, str] = {}  # import_path -> alias
    for m in RX_EXISTING_IMPORT.finditer(source):
        existing_imports[m.group(1)] = m.group(2)

    # Find all component tags
    tags = find_component_tags(source)

    # Resolve each tag to a component and plan imports
    imports_to_add: dict[str, str] = {}  # import_path -> alias
    tag_renames: dict[str, str] = {}     # old_tag -> new_alias
    alias_counts: dict[str, list[str]] = {}  # alias -> [jinjax_names]

    for tag in sorted(tags):
        info = registry.resolve(tag)
        if info is None:
            continue  # Not a known component (could be HTML element)

        # Already imported?
        if info.import_path in existing_imports:
            alias = existing_imports[info.import_path]
            if tag != alias:
                tag_renames[tag] = alias
            continue

        # Determine alias
        alias = registry.get_alias(info)

        # Track collisions
        if alias not in alias_counts:
            alias_counts[alias] = []
        alias_counts[alias].append(info.jinjax_name)

        imports_to_add[info.import_path] = alias
        if tag != alias:
            tag_renames[tag] = alias

    # Resolve alias collisions
    for alias, names in alias_counts.items():
        if len(names) <= 1:
            continue
        warnings.append(
            f"Alias collision for '{alias}': {names}. "
            "Using qualified names."
        )
        for name in names:
            info = registry.resolve(name)
            if info is None:
                continue
            # Build a longer alias from the full name
            qualified = name.replace(":", "").replace(".", "")
            qualified = to_pascal_case(qualified)
            imports_to_add[info.import_path] = qualified
            tag_renames[name] = qualified

    # Rename tags in source
    for old_tag, new_alias in tag_renames.items():
        # Escape dots and colons for regex
        escaped = re.escape(old_tag)
        # Opening tags: <old.Tag -> <NewAlias
        source = re.sub(
            rf"<(?P<slash>/?)(?P<tag>{escaped})(?P<after>\s|\n|/|>)",
            rf"<\g<slash>{new_alias}\g<after>",
            source,
        )

    # Build import lines
    import_lines: list[str] = []
    for imp_path, alias in sorted(imports_to_add.items()):
        if imp_path not in existing_imports:
            import_lines.append(f'{{#import "{imp_path}" as {alias} #}}')

    # Insert imports at the top of the file
    if import_lines:
        import_block = "\n".join(import_lines) + "\n"

        # Find insertion point: before any existing metadata
        meta_match = RX_META_HEADER.match(source)
        existing_import_matches = list(RX_EXISTING_IMPORT.finditer(source))

        if existing_import_matches:
            # After last existing import
            last = existing_import_matches[-1]
            nl = source.find("\n", last.end())
            insert_pos = (nl + 1) if nl != -1 else last.end()
        elif meta_match:
            insert_pos = meta_match.start()
        else:
            insert_pos = 0

        source = source[:insert_pos] + import_block + source[insert_pos:]

    # Restore raw blocks
    source = restore_raw_blocks(source, raw_placeholders)

    return source, warnings


# ---------------------------------------------------------------------------
# Orchestrator: transform a single file
# ---------------------------------------------------------------------------


def transform_file(
    file_path: Path,
    registry: ComponentRegistry,
    url_prefix: str,
) -> FileChanges:
    """Apply all transformations to a single .jinja file."""
    original = file_path.read_text(encoding="utf-8")
    source = original
    all_warnings: list[str] = []

    # Determine if this file is a known component (for asset handling)
    component_info: ComponentInfo | None = None
    for info in registry.components.values():
        if info.file_path == file_path:
            component_info = info
            break

    # Phase 3a: Migrate slot definitions
    source = migrate_slot_definitions(source)

    # Phase 3b: Migrate slot usage
    source, slot_warnings = migrate_slot_usage(source)
    all_warnings.extend(slot_warnings)

    # Phase 3c: Update asset rendering calls
    source = migrate_asset_rendering(source)

    # Phase 3d: Add auto-discovered asset declarations
    source = add_auto_assets(source, component_info, url_prefix)

    # Phase 3e: Update existing asset declaration paths
    source = update_asset_paths(source, component_info, url_prefix)

    # Phase 3f: Generate imports and rename tags (MUST be last)
    source, import_warnings = generate_imports_and_rename(
        source, file_path, registry
    )
    all_warnings.extend(import_warnings)

    return FileChanges(
        file_path=file_path,
        original=original,
        transformed=source,
        warnings=all_warnings,
    )


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def create_backup(
    files: list[Path],
    asset_sources: list[Path],
    backup_dir: Path,
) -> Path:
    """Create timestamped backup of all files that will be modified."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"backup-{timestamp}"
    backup_path.mkdir(parents=True, exist_ok=True)

    for f in files + asset_sources:
        if f.exists():
            # Use the absolute path (minus root) to guarantee uniqueness
            dest = backup_path / f.resolve().relative_to(f.resolve().anchor)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)

    return backup_path


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_diff_summary(changes: FileChanges) -> None:
    """Print a concise summary of changes to a file."""
    if not changes.changed:
        return

    print(f"\n  --- {changes.file_path} ---")

    old_lines = changes.original.splitlines(keepends=True)
    new_lines = changes.transformed.splitlines(keepends=True)

    # Show added/removed lines (simple diff)
    old_set = set(old_lines)
    new_set = set(new_lines)

    for line in new_lines:
        if line not in old_set:
            print(f"    + {line.rstrip()}")
    for line in old_lines:
        if line not in new_set:
            print(f"    - {line.rstrip()}")

    for w in changes.warnings:
        print(f"    ! WARNING: {w}")


def print_report(result: MigrationResult) -> None:
    """Print the full migration report."""
    changed = [c for c in result.file_changes if c.changed]

    if not changed and not result.asset_copies:
        print("\nNo changes needed.")
        return

    print(f"\n{'='*60}")
    print("MIGRATION REPORT")
    print(f"{'='*60}")

    if changed:
        print(f"\nTemplates to modify: {len(changed)}")
        for c in changed:
            print_diff_summary(c)

    if result.asset_copies:
        print(f"\nAssets to copy: {len(result.asset_copies)}")
        for src, dest in result.asset_copies:
            print(f"    {src} -> {dest}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    ! {w}")

    # Summary stats
    imports_added = 0
    slots_migrated = 0
    fills_migrated = 0
    asset_calls_migrated = 0
    for c in changed:
        new = c.transformed
        old = c.original
        imports_added += len(RX_EXISTING_IMPORT.findall(new)) - len(
            RX_EXISTING_IMPORT.findall(old)
        )
        # Count slot/fill changes
        slots_migrated += new.count("{% slot ") - old.count("{% slot ")
        fills_migrated += new.count("{% fill ") - old.count("{% fill ")
        asset_calls_migrated += old.count("catalog.render_assets()") - new.count(
            "catalog.render_assets()"
        )

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Templates modified:        {len(changed)}")
    print(f"  Import statements added:   {imports_added}")
    print(f"  Slot definitions migrated: {slots_migrated}")
    print(f"  Fill blocks generated:     {fills_migrated}")
    print(f"  Asset calls migrated:      {asset_calls_migrated}")
    print(f"  Asset files to copy:       {len(result.asset_copies)}")
    print()


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def prompt_catalog_folders() -> list[CatalogFolder]:
    """Interactively ask for catalog folder paths and prefixes."""
    folders: list[CatalogFolder] = []
    print("\nStep 1: Configure catalog folders")
    print("  Enter component folder paths. Press Enter when finished.\n")

    while True:
        path_str = input("  Component folder path: ").strip()
        if not path_str:
            if not folders:
                print("  You must add at least one folder.")
                continue
            break

        path = Path(path_str).resolve()
        if not path.is_dir():
            print(f"  Error: '{path}' is not a valid directory.")
            continue

        prefix = input("  Prefix for this folder (empty for none): ").strip()
        folders.append(CatalogFolder(path=path, prefix=prefix))
        print(f"  Added: {path}" + (f" (prefix: {prefix})" if prefix else ""))
        print()

    return folders


def prompt_static_folder() -> Path:
    """Ask for the static folder path."""
    print("\nStep 2: Configure static folder")
    while True:
        path_str = input("  Static folder path: ").strip()
        path = Path(path_str).resolve()
        if path.exists() and not path.is_dir():
            print(f"  Error: '{path}' exists but is not a directory.")
            continue
        return path


def prompt_url_prefix() -> str:
    """Ask for the asset URL prefix."""
    print("\nStep 3: Configure asset URL prefix")
    prefix = input("  URL prefix [/static/]: ").strip()
    if not prefix:
        prefix = "/static/"
    # Ensure trailing slash
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate JinjaX templates to Jx syntax."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backups before modifying files.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  JinjaX -> Jx Migration Tool")
    print("=" * 60)

    # Gather configuration
    folders = prompt_catalog_folders()
    static_folder = prompt_static_folder()
    url_prefix = prompt_url_prefix()

    # Phase 1: Build component registry
    print("\nStep 4: Scanning components...")
    registry = ComponentRegistry()
    total = 0
    for folder in folders:
        count = registry.add_folder(folder)
        label = f" (prefix: {folder.prefix})" if folder.prefix else " (no prefix)"
        print(f"  Found {count} components in {folder.path}{label}")
        total += count
    print(f"  Total: {total} components")

    if total == 0:
        print("\nNo components found. Nothing to migrate.")
        return

    # Phase 2: Plan asset copies
    asset_copies = plan_asset_copies(registry, static_folder, url_prefix)

    # Phase 3: Transform templates
    print("\nStep 5: Analyzing templates...")
    result = MigrationResult(asset_copies=asset_copies)

    # Collect all .jinja files from all catalog folders
    all_jinja_files: list[Path] = []
    for folder in folders:
        all_jinja_files.extend(sorted(folder.path.resolve().rglob("*.jinja")))

    for jinja_file in all_jinja_files:
        changes = transform_file(jinja_file, registry, url_prefix)
        result.file_changes.append(changes)
        if changes.warnings:
            result.warnings.extend(
                f"{jinja_file.name}: {w}" for w in changes.warnings
            )

    # Report
    print_report(result)

    changed_files = [c for c in result.file_changes if c.changed]

    if not changed_files and not asset_copies:
        return

    if args.dry_run:
        print("  (dry-run mode -- no files modified)\n")
        return

    # Confirm
    answer = input("Apply changes? (y/n): ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    # Backup
    script_dir = Path(__file__).resolve().parent
    if not args.no_backup:
        backup_files = [c.file_path for c in changed_files]
        asset_srcs = [src for src, _ in asset_copies]
        backup_path = create_backup(
            backup_files, asset_srcs, script_dir / "backups"
        )
        print(f"\n  Backup created: {backup_path}")

    # Apply template changes
    for changes in changed_files:
        changes.file_path.write_text(changes.transformed, encoding="utf-8")
    print(f"  Modified {len(changed_files)} template(s)")

    # Apply asset copies
    execute_asset_copies(asset_copies, dry_run=False)
    print(f"  Copied {len(asset_copies)} asset file(s)")

    print("\nMigration complete!")


if __name__ == "__main__":
    main()
