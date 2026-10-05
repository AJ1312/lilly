"""The layering is enforced, not just documented: a layer may import only from layers below it."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "lilly"
RANK = {"domain": 0, "obs": 0, "core": 1, "store": 2, "providers": 3, "tools": 3, "decide": 3, "engine": 4, "app": 5,
        "ui": 6, "bridges": 6, "daemon": 7}
SIBLING_GROUPS = ({"providers", "tools", "decide"}, {"ui", "bridges"})  # same rank, must stay independent of each other


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("lilly."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[1] for a in node.names if a.name.startswith("lilly.")}
    return found


FILES = sorted(p for p in SRC.rglob("*.py") if p.relative_to(SRC).parts[0] in RANK)


def test_every_package_has_a_rank() -> None:
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert packages - {"web"} == set(RANK)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_layer_only_imports_downward(path: Path) -> None:
    layer = path.relative_to(SRC).parts[0]
    for target in imports(path) - {layer}:
        if target not in RANK:
            continue  # lilly.__version__ and similar
        assert RANK[target] <= RANK[layer], f"{layer} must not import {target}"
        assert not any(layer in g and target in g for g in SIBLING_GROUPS), f"{layer} must not import its sibling {target}"
