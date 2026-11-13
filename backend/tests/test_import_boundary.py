"""Architectural test: the agent package must not be able to execute tools.

A permission check the agent could skip by importing a function directly is
theatre. This test parses every module under app/agent/ and fails if any of
them imports app.tools (where the real, database-touching implementations
live). The agent may import app.schemas.tool_catalog, which is inert.

If this test ever fails, the central claim of the project is false.
"""
import ast
import pathlib

AGENT_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "agent"
FORBIDDEN_PREFIX = "app.tools"


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_agent_package_never_imports_tool_implementations():
    offenders: list[str] = []
    files = sorted(AGENT_DIR.rglob("*.py"))
    assert files, "no agent modules found -- check the path"

    for path in files:
        for module in _imported_modules(path):
            if module == FORBIDDEN_PREFIX or module.startswith(FORBIDDEN_PREFIX + "."):
                offenders.append(f"{path.name} imports {module}")

    assert not offenders, (
        "The agent package must reach tools only via the governance engine. "
        f"Violations: {offenders}"
    )


def test_every_catalog_entry_has_exactly_one_implementation():
    """Guards the other direction: a tool the model can see but the registry
    cannot run (or vice versa) is a silent failure."""
    from app.schemas.tool_catalog import TOOL_CATALOG
    from app.tools.registry import TOOL_REGISTRY

    assert set(TOOL_CATALOG) == set(TOOL_REGISTRY)
