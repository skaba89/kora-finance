"""Garde-fous statiques sur le code source (règles non négociables de CLAUDE.md).

Analyse de l'AST plutôt que du texte : les commentaires et docstrings qui
mentionnent une pratique interdite ne déclenchent pas de faux positif.
"""

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted([*(API_ROOT / "src").rglob("*.py"), *(API_ROOT / "alembic").rglob("*.py")])


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def calls_create_all(node: ast.Call) -> bool:
    """Le schéma est géré exclusivement par Alembic."""
    return _called_name(node) == "create_all"


def interpolated_sql(node: ast.Call) -> bool:
    """`text(f"...")` ou `text("..." % x)` / `.format()` = injection SQL potentielle."""
    if _called_name(node) != "text" or not node.args:
        return False
    arg = node.args[0]
    return (
        isinstance(arg, ast.JoinedStr)
        or (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod | ast.Add))
        or (isinstance(arg, ast.Call) and _called_name(arg) == "format")
    )


RULES: dict[str, Callable[[ast.Call], bool]] = {
    "create_all() interdit : passer par une migration Alembic": calls_create_all,
    "SQL interpolé interdit : utiliser des paramètres liés": interpolated_sql,
}


def offenders(source: str, rule: Callable[[ast.Call], bool]) -> list[int]:
    tree = ast.parse(source)
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and rule(n)]


@pytest.mark.parametrize("message", RULES)
def test_regle_respectee_dans_le_code(message: str) -> None:
    found = [
        f"{path.relative_to(API_ROOT)}:{line}"
        for path in SOURCES
        for line in offenders(path.read_text(encoding="utf-8"), RULES[message])
    ]
    assert not found, f"{message} — {found}"


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("Base.metadata.create_all(engine)", calls_create_all),
        ('text(f"SELECT * FROM t WHERE id = {x}")', interpolated_sql),
        ('text("SELECT * FROM t WHERE id = %s" % x)', interpolated_sql),
        ('text("SELECT * FROM t WHERE id = " + x)', interpolated_sql),
        ('text("SELECT {}".format(x))', interpolated_sql),
    ],
)
def test_le_garde_fou_detecte_les_violations(source: str, rule: Callable[[ast.Call], bool]) -> None:
    assert offenders(source, rule) == [1]


def test_le_garde_fou_ignore_commentaires_et_sql_parametre() -> None:
    source = '"""Ne jamais appeler metadata.create_all()."""\ntext("SELECT 1 WHERE id = :id")\n'
    assert offenders(source, calls_create_all) == []
    assert offenders(source, interpolated_sql) == []
