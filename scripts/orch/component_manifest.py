#!/usr/bin/env python3
"""The per-app COMPONENT MANIFEST — a project-specific artifact that makes a
generated app's components discoverable and REUSABLE.

ADF generates modular, props-driven React components (one self-contained component
per concern under `src/components/`). This module scans them deterministically after
a verified build, captures each component's public API (its exported props), and
writes `.adf-components.json` + a human `COMPONENTS.md`. On the next edit/feature the
manifest is fed back to the model so it REUSES existing components instead of
duplicating them — composability by construction.
"""
import json
import os
import re
import sys

# A component export: `export [default] function Foo` / `export [default] const Foo =`.
# Require PascalCase WITH a lowercase tail so ALL-CAPS constants (MAX, API_URL) and
# acronyms are not mistaken for components.
_COMPONENT_EXPORT = re.compile(
    r'export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class)\s+'
    r'([A-Z][a-z]\w*)')
# A props type: `interface FooProps { ... }` or `type FooProps = { ... }`.
_PROPS_TYPE = re.compile(r'(?:interface|type)\s+(\w+Props)\s*=?\s*\{([^}]*)\}', re.S)
# One prop within the body (props may be `;`- or newline-separated on one line).
_PROP_SEG = re.compile(r'^\s*(\w+)(\?)?\s*:\s*(.+)$')

_SKIP_FILES = {"main.tsx"}
_FORMAT = "adf-components/1"


def _components_in(text):
    seen, out = set(), []
    for m in _COMPONENT_EXPORT.finditer(text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _props_in(text):
    """Map of `<Name>Props` → [{name, type, optional}], best-effort."""
    props = {}
    for m in _PROPS_TYPE.finditer(text):
        plist = []
        for seg in re.split(r"[;\n]", m.group(2)):
            pm = _PROP_SEG.match(seg)
            if pm:
                plist.append({
                    "name": pm.group(1),
                    "optional": bool(pm.group(2)),
                    "type": pm.group(3).strip().rstrip(",").strip(),
                })
        props[m.group(1)] = plist
    return props


def extract_components(app_dir):
    """Every exported component under src/**.tsx (except the bootstrap), with its
    file path, role (root composer vs reusable component), and props API."""
    src = os.path.join(app_dir, "src")
    out = []
    if not os.path.isdir(src):
        return out
    for root, _dirs, files in os.walk(src):
        for fn in sorted(files):
            if not fn.endswith(".tsx") or fn in _SKIP_FILES:
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            rel = os.path.relpath(fp, app_dir)
            propsmap = _props_in(text)
            for name in _components_in(text):
                role = "root" if (name == "App" or fn == "App.tsx") else "component"
                out.append({
                    "name": name,
                    "path": rel,
                    "role": role,
                    "props": propsmap.get(f"{name}Props", []),
                })
    return out


def render_markdown(components):
    lines = [
        "# Components",
        "",
        f"{len(components)} component(s) in this app. Each is self-contained and "
        "props-driven — reuse it in another feature by importing it and passing its "
        "props. Generated from `src/components/` by ADF.",
        "",
    ]
    for c in components:
        tag = " *(composition root)*" if c["role"] == "root" else ""
        lines.append(f"## `{c['name']}`{tag} — `{c['path']}`")
        if c["props"]:
            lines.append("")
            lines.append("| prop | type | required |")
            lines.append("|---|---|:--:|")
            for p in c["props"]:
                lines.append(
                    f"| `{p['name']}` | `{p['type']}` | "
                    f"{'—' if p['optional'] else '✓'} |")
        else:
            lines.append("")
            lines.append("_No props — drop-in._")
        lines.append("")
    return "\n".join(lines)


def generate(app_dir):
    """Scan + write the manifest. Returns the manifest dict."""
    components = extract_components(app_dir)
    data = {"format": _FORMAT, "count": len(components), "components": components}
    with open(os.path.join(app_dir, ".adf-components.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(os.path.join(app_dir, "COMPONENTS.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(components))
    return data


def manifest_summary(app_dir):
    """A compact one-line-per-component summary for feeding into an edit prompt so
    a new feature REUSES existing components. Empty string if none."""
    p = os.path.join(app_dir, ".adf-components.json")
    if not os.path.isfile(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    lines = []
    for c in data.get("components", []):
        if c.get("role") == "root":
            continue
        props = ", ".join(
            f"{x['name']}{'?' if x['optional'] else ''}: {x['type']}"
            for x in c.get("props", []))
        lines.append(f"- <{c['name']}> ({c['path']}) props: {{{props}}}")
    return "\n".join(lines)


def _main(argv=None):
    app = (argv or sys.argv[1:] or ["."])[0]
    data = generate(app)
    print(f"{data['count']} component(s) → {app}/.adf-components.json + COMPONENTS.md")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
