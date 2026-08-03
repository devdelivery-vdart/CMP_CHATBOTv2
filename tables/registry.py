"""
Auto-discovers every TableSpec registered in the `tables/` folder.

This is what makes adding a new table "seamless": nothing outside this
folder needs to change. Drop a new file in `tables/` following the
candidates_masked.py pattern, and it's picked up automatically here.
"""

import importlib
import pkgutil

from tables.base import TableSpec

_REGISTRY: dict[str, TableSpec] = {}


def _discover():
    import tables as tables_pkg

    for _, module_name, _ in pkgutil.iter_modules(tables_pkg.__path__):
        if module_name in ("base", "registry"):
            continue
        module = importlib.import_module(f"tables.{module_name}")
        spec = getattr(module, "TABLE", None)
        if isinstance(spec, TableSpec) and spec.enabled:
            _REGISTRY[spec.name] = spec


_discover()


def allowed_table_names() -> set[str]:
    """The full allow-list, used by sql_guard.py to reject queries on
    anything not registered here."""
    return set(_REGISTRY.keys())


def combined_schema_text() -> str:
    """All enabled tables' descriptions, concatenated, to feed the LLM."""
    return "\n\n".join(spec.description for spec in _REGISTRY.values())


def combined_examples_text() -> str:
    """
    All registered few-shot examples (question -> SQL pairs), formatted
    for inclusion in the system prompt. Returns "" if none are registered.
    """
    all_examples = []
    for spec in _REGISTRY.values():
        all_examples.extend(spec.examples)

    if not all_examples:
        return ""

    lines = ["Examples of correctly-answered questions for this schema:"]
    for ex in all_examples:
        lines.append(f'\nQ: "{ex.question}"\nSQL: {ex.sql}')
    return "\n".join(lines)


def all_specs() -> list[TableSpec]:
    return list(_REGISTRY.values())
