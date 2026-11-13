"""Risk classification.

Risk is a property of the tool, declared in the registry, not something the
model reports about itself. A model that could nominate its own risk level
could nominate LOW for everything.
"""
from app.models.enums import RiskLevel

#: Risk levels that require a human decision before execution.
REQUIRES_APPROVAL: frozenset[RiskLevel] = frozenset({RiskLevel.HIGH})


def requires_approval(risk: RiskLevel) -> bool:
    return risk in REQUIRES_APPROVAL
