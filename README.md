# JinjaX-to-Jx Migration Script

This script automates migrating [JinjaX](https://github.com/jpsca/jinjax/) templates and their co-located CSS/JS assets to [Jx](https://github.com/jpsca/jx/) syntax.

**Scope**: Templates and assets only. Python integration code (Catalog setup, middleware removal) is left to the user.

## Templates & Assets

### User Interaction Flow

```
$ python migrate.py [--dry-run] [--no-backup]

1. Prompt for catalog folder(s) with optional prefix per folder (loop until empty)
2. Prompt for static folder path
3. Prompt for asset URL prefix (e.g. /static/)
4. Scan & report component count
5. Show preview of all changes
6. If not --dry-run, confirm and apply
```

### Phase 1: Build Component Registry (read-only scan)

Recursively scan each catalog folder for `*.jinja` files. For each, compute:

| Field                       | Example
| --------------------------- |--------
| JinjaX name                 | `Card`, `common.Form`, `ui:Button`
| File path                   | `/abs/path/to/card.jinja`
| Jx import path              | `"card.jinja"`, `"common/form.jinja"`, `"@ui/button.jinja"`
| Has co-located `.css`/`.js` | `True`/`False`

Name resolution rules (from JinjaX's `catalog.py`):
- Dots map to subfolders: `common.Form` -> `common/Form.jinja` (also check `common/form.jinja` kebab variant)
- Colons map to prefixes: `ui:Button` -> `Button.jinja` in the `ui`-prefixed folder
- `subfolder/index.jinja` -> component name is the subfolder name

### Phase 2: Move Asset Files

Copy `.css`/`.js` files from component folders to the static folder, preserving subfolder structure. Prefixed folders nest under their prefix name.

```
components/Card.css          -> static/components/card.css
components/common/Form.css   -> static/components/common/form.css
vendor-ui/Button.css         -> static/components/ui/button.css  (prefix: ui)
```

Do NOT delete originals (user can do so manually).

### Phase 3: Transform Each `.jinja` File

Apply these transformations in order per file:

#### 3a. Migrate slot definitions

In component templates that define named slots:

```
{{ content("header") }}     ->  {% slot header %}{% endslot %}
{{ content() }}             ->  {{ content }}
```

#### 3b. Migrate slot usage

In templates that fill named slots via `_slot` conditionals:

```jinja
{# BEFORE (JinjaX) #}                    {# AFTER (Jx) #}
{% if _slot == "header" %}                {% fill header %}
  <h1>Title</h1>                            <h1>Title</h1>
{% elif _slot == "footer" %}              {% endfill %}
  <p>Footer</p>                           {% fill footer %}
{% else %}                                  <p>Footer</p>
  Default body                            {% endfill %}
{% endif %}                               Default body
```

#### 3c. Update asset rendering calls

```
{{ catalog.render_assets() }}  ->  {{ assets.render() }}
```

#### 3d. Add auto-discovered asset declarations

JinjaX auto-discovers `Card.css` alongside `Card.jinja`. Jx doesn't. If the file exists but no `{#css ...#}` declaration references it, add one with the new static URL:

```
{#css /static/components/card.css #}
```

Insert after any existing `{#css#}`/`{#js#}` lines, before `{#def#}`.

#### 3e. Update existing asset declaration paths

For each path in `{#css ...#}` and `{#js ...#}`:
- `http://` / `https://` URLs: leave unchanged
- Paths starting with `/`: leave unchanged
- Relative paths: prepend the user-configured URL prefix

```
{#css card.css #}  ->  {#css /static/components/card.css #}
```

For prefixed components, include the prefix in the path: `/static/components/ui/button.css`.

#### 3f. Generate imports and rename tags (LAST)

This must run last because it renames tags, which would break earlier pattern matching.

1. Find all PascalCase component tags with `RX_TAG_NAME` (protecting `{% raw %}` blocks)
2. Look each up in the component registry; skip unknown tags (they're HTML elements)
3. Generate `{#import "path" as Alias #}` for each unique component used
4. Rename dotted/prefixed tags in the template body:
   - `<common.Form>` / `</common.Form>` -> `<Form>` / `</Form>`
   - `<ui:Button />` -> `<Button />`
5. Insert imports at the top of the file, before `{#css#}`/`{#js#}`/`{#def#}`

Alias collision handling: if two components resolve to the same alias (e.g. `common.Card` and `special.Card` both -> `Card`), use the longer qualified name (`CommonCard`, `SpecialCard`) and warn.

### Edge Cases

- **`{% raw %}` blocks**: Replace with UUID placeholders before scanning, restore after (same approach both libraries use)
- **Idempotency**: Check for existing `{#import#}` statements before adding duplicates
- **Nested `{% if %}` inside `_slot` blocks**: Track nesting depth; only migrate the outermost `_slot` conditional
- **Mixed `_slot`/non-`_slot` conditionals**: Warn, don't transform
- **Shared assets**: Copy each file only once even if referenced by multiple components
- **Kebab-case filenames**: `my-button.jinja` -> import alias `MyButton`
- **Index files**: `tab/index.jinja` referenced as `<Tab>` -> `{#import "tab/index.jinja" as Tab #}`

### Backup Strategy

Before modifying any file, create `backups/YYYYMMDD-HHMMSS/` mirroring the directory structure of all affected files. Skip with `--no-backup`.


## Python Code Changes (Manual)

After running the migration script, you need to update your Python integration code. Here's what changes for each framework.

### 1. Replace the package

```bash
pip uninstall jinjax
pip install jx
```

### 2. Update imports

```python
# Before
import jinjax
# or
from jinjax import Catalog, JinjaX

# After
import jx
# or
from jx import Catalog
```

### 3. Update Catalog construction

JinjaX's `Catalog` takes all keyword arguments. Jx's `Catalog` accepts a positional `folder` shortcut and passes globals as `**kwargs`.

```python
# Before (JinjaX)
catalog = jinjax.Catalog(
    globals={"site_name": "My Site"},
)
catalog.add_folder("components/")

# After (Jx)
catalog = jx.Catalog(
    "components/",                     # optional folder shortcut (new)
    site_name="My Site",               # globals are now **kwargs, not a dict
)
```

Key differences:
- `globals={"key": val}` dict → pass as `**kwargs` directly: `key=val`
- `root_url`, `file_ext`, `use_cache`, `fingerprint` → removed (Jx doesn't serve assets)
- `folder` → optional first positional argument (shortcut for `add_folder`)

### 4. Update `render` calls

```python
# Before (JinjaX)
html = catalog.render("ComponentName", arg1="value", arg2=42)
# Component name used dot notation: "common.Form"

# After (Jx)
html = catalog.render("component-name.jinja", arg1="value", arg2=42)
# Uses file path with extension: "common/form.jinja"
```

Key differences:
- JinjaX uses PascalCase dot-notation component names: `"Card"`, `"common.Form"`
- Jx uses file paths with extension: `"card.jinja"`, `"common/form.jinja"`
- Jx also accepts a `globals` dict parameter for per-render globals:

```python
html = catalog.render(
    "page.jinja",
    globals={"request": request, "csrf_token": token},
    title="Dashboard",
)
```

### 5. Remove the middleware

JinjaX requires WhiteNoise middleware to serve component CSS/JS. Jx doesn't — assets are just URLs served by your existing static file setup.

```python
# Before (JinjaX) — DELETE THIS
app.wsgi_app = catalog.get_middleware(app.wsgi_app)
```

Make sure your web framework's static file configuration serves the folder you chose during migration (the static folder) at the URL prefix you chose.

### 6. Update special render parameters

```python
# Before (JinjaX)
html = catalog.render("Card", _content="<p>Hi</p>", _source="...", _globals={...})
# Also accepted legacy: __content, __source, __globals

# After (Jx) — these don't exist
# Use catalog.render_string() for inline source:
html = catalog.render_string("{#def name #}<p>{{ name }}</p>", name="Hi")
# Pass globals via the globals parameter:
html = catalog.render("card.jinja", globals={"request": req}, title="Hi")
```

### Framework-Specific Examples

#### Flask

```python
# Before
import jinjax

app = Flask(__name__)
catalog = jinjax.Catalog(jinja_env=app.jinja_env)
catalog.add_folder("components")
app.wsgi_app = catalog.get_middleware(app.wsgi_app, autorefresh=app.debug)

@app.route("/")
def index():
    return catalog.render("Page", title="Home")

# After
import jx

app = Flask(__name__)
catalog = jx.Catalog("components", jinja_env=app.jinja_env)

@app.route("/")
def index():
    return catalog.render("page.jinja", title="Home")
```

#### Django (with django-jinja or manual Jinja2 setup)

```python
# Before
import jinjax

env.add_extension(jinjax.JinjaX)
catalog = jinjax.Catalog(jinja_env=env)
catalog.add_folder("components")

# After
import jx

catalog = jx.Catalog("components", jinja_env=env)
```

#### FastAPI

```python
# Before
import jinjax

templates = Jinja2Templates(directory="templates")
templates.env.add_extension(jinjax.JinjaX)
catalog = jinjax.Catalog(jinja_env=templates.env)
catalog.add_folder("templates/components")

# After
import jx

catalog = jx.Catalog("templates/components", jinja_env=templates.env)
```

### Summary Checklist

- [ ] `pip install jx` and uninstall `jinjax`
- [ ] `import jinjax` → `import jx`
- [ ] `jinjax.Catalog(...)` → `jx.Catalog(...)` with updated args
- [ ] `globals={...}` dict → `**kwargs`
- [ ] Remove `root_url`, `file_ext`, `use_cache`, `fingerprint` params
- [ ] `catalog.render("ComponentName", ...)` → `catalog.render("component-name.jinja", ...)`
- [ ] Remove `catalog.get_middleware(...)` call
- [ ] Configure your static file server to serve the migrated assets
- [ ] Remove `jinja2.ext.do` from explicit extensions (Jx adds it automatically if needed)

## Verification

1. Run `python migrate.py --dry-run` on a test catalog folder with known components
2. Verify import generation: each used component gets a correct `{#import#}` line
3. Verify slot migration: `content("name")` -> `{% slot %}`, `_slot` conditionals -> `{% fill %}`
4. Verify asset files are copied to the static folder with correct structure
5. Verify `{#css#}`/`{#js#}` paths point to the new static location
6. Verify `catalog.render_assets()` -> `assets.render()`
7. Render a migrated template with Jx's `Catalog` and confirm it produces equivalent HTML
