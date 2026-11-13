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

#: Modules the agent package may never import.
#:   app.tools              -- the real implementations
#:   app.governance.approvals / .action_requests
#:                          -- the approval machinery. If the agent could
#:                             reach these it could approve its own
#:                             high-risk actions, which is the single thing
#:                             the whole approval workflow exists to prevent.
FORBIDDEN_PREFIXES = (
    "app.tools",
    "app.governance.approvals",
    "app.governance.action_requests",
)


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _violates(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in FORBIDDEN_PREFIXES
    )


def test_agent_package_never_imports_tool_implementations():
    offenders: list[str] = []
    files = sorted(AGENT_DIR.rglob("*.py"))
    assert files, "no agent modules found -- check the path"

    for path in files:
        for module in _imported_modules(path):
            if _violates(module):
                offenders.append(f"{path.name} imports {module}")

    assert not offenders, (
        "The agent package must reach tools only via the governance engine, "
        "and must have no path at all to the approval machinery. "
        f"Violations: {offenders}"
    )


def test_agent_cannot_reach_approvals_transitively():
    """The direct-import ban is not enough on its own.

    app.agent.orchestrator imports app.governance.engine, so if the engine
    ever imported the approval service, the agent would acquire a path to
    it through the back door. The engine may create an action request; it
    may never decide on one.
    """
    import app.governance.engine as engine_module

    source = pathlib.Path(engine_module.__file__).read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    assert "app.governance.approvals" not in imported, (
        "The engine must not import the approval service -- that would give "
        "the agent a transitive path to approving its own actions."
    )


def test_every_catalog_entry_has_exactly_one_implementation():
    """Guards the other direction: a tool the model can see but the registry
    cannot run (or vice versa) is a silent failure."""
    from app.schemas.tool_catalog import TOOL_CATALOG
    from app.tools.registry import TOOL_REGISTRY

    assert set(TOOL_CATALOG) == set(TOOL_REGISTRY)
