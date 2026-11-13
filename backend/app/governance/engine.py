"""The governance engine.

THE CENTRAL INVARIANT OF THIS SYSTEM:

    The LLM never executes anything. It only emits a request.
    This engine is the sole caller of every tool implementation.

Order of checks is deliberate. Cheapest and most absolute first, so that a
disabled agent cannot even cause a permission lookup, and an unknown tool
name never reaches a Pydantic model.

    1. kill switch      -- is this agent enabled at all?
    2. tool exists      -- is the name in the registry?
    3. schema validation-- do the params match the declared model?
    4. permission       -- does this agent hold the required permission?
    5. risk             -- does this risk level need a human?
    6. execute          -- only now, and only via registry.impl

Every path writes exactly one audit row, including every rejection.
"""
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.governance.audit import write_audit
from app.governance.kill_switch import is_agent_enabled
from app.governance.permissions import agent_has_permission
from app.governance.risk import requires_approval
from app.models.enums import (
    ApprovalStatus, Outcome, PermissionResult, RiskLevel,
)
from app.tools.appointments import ToolExecutionError
from app.tools.registry import get_tool


@dataclass
class GovernanceResult:
    """What the orchestrator gets back. Never raises for policy decisions --
    a block is a normal, expected outcome that the agent must be told about
    so it can explain it to the customer."""
    outcome: Outcome
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    audit_log_id: int | None = None
    risk_level: RiskLevel | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome is Outcome.EXECUTED

    def to_tool_result(self) -> dict[str, Any]:
        """The payload handed back to the model as a tool_result block.

        On a block, the model is told WHAT happened but is given no hint
        that retrying or rephrasing could succeed.
        """
        if self.outcome is Outcome.EXECUTED:
            return {"status": "ok", **self.data}
        return {"status": self.outcome.value, "message": self.message}


class GovernanceEngine:
    def __init__(self, db: Session, agent_id: int, conversation_id: int | None = None):
        self.db = db
        self.agent_id = agent_id
        self.conversation_id = conversation_id

    def _audit(self, **kwargs) -> int:
        entry = write_audit(
            self.db,
            agent_id=self.agent_id,
            conversation_id=self.conversation_id,
            **kwargs,
        )
        return entry.id

    def execute(self, tool_name: str, raw_params: dict[str, Any]) -> GovernanceResult:
        # --- 1. Emergency stop -------------------------------------------
        if not is_agent_enabled(self.db, self.agent_id):
            log_id = self._audit(
                tool_name=tool_name, params=raw_params, risk_level=None,
                permission_result=None, approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.BLOCKED,
                error_message="Agent is disabled (emergency stop engaged).",
            )
            return GovernanceResult(
                outcome=Outcome.BLOCKED,
                message="The assistant is currently disabled by an administrator.",
                audit_log_id=log_id,
            )

        # --- 2. Is this a tool we actually have? -------------------------
        spec = get_tool(tool_name)
        if spec is None:
            log_id = self._audit(
                tool_name=tool_name, params=raw_params, risk_level=None,
                permission_result=None, approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.BLOCKED,
                error_message=f"Unknown tool '{tool_name}'.",
            )
            return GovernanceResult(
                outcome=Outcome.BLOCKED,
                message=f"No such tool: {tool_name}.",
                audit_log_id=log_id,
            )

        # --- 3. Schema validation ----------------------------------------
        try:
            params = spec.params_model.model_validate(raw_params)
        except ValidationError as exc:
            log_id = self._audit(
                tool_name=tool_name, params=raw_params, risk_level=spec.risk_level,
                permission_result=None, approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.BLOCKED, error_message=f"Invalid parameters: {exc}",
            )
            return GovernanceResult(
                outcome=Outcome.BLOCKED,
                message="The request was missing required information.",
                audit_log_id=log_id, risk_level=spec.risk_level,
            )

        # --- 4. Permission -----------------------------------------------
        if not agent_has_permission(self.db, self.agent_id, spec.required_permission):
            log_id = self._audit(
                tool_name=tool_name, params=raw_params, risk_level=spec.risk_level,
                permission_result=PermissionResult.FAIL,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.BLOCKED,
                error_message=(
                    f"Agent lacks permission {spec.required_permission.value}."
                ),
            )
            return GovernanceResult(
                outcome=Outcome.BLOCKED,
                message=(
                    "I'm not authorised to do that. I can pass this to a "
                    "member of staff instead."
                ),
                audit_log_id=log_id, risk_level=spec.risk_level,
            )

        # --- 5. Risk / approval ------------------------------------------
        if requires_approval(spec.risk_level):
            # Milestone 2 creates an ActionRequest row here and resumes on
            # approval. For now execution is withheld, which is the part
            # that must never regress.
            log_id = self._audit(
                tool_name=tool_name, params=params.model_dump(),
                risk_level=spec.risk_level,
                permission_result=PermissionResult.PASS,
                approval_status=ApprovalStatus.PENDING,
                outcome=Outcome.PENDING_APPROVAL,
                error_message=None,
            )
            return GovernanceResult(
                outcome=Outcome.PENDING_APPROVAL,
                message=(
                    "That action needs approval from a member of staff. "
                    "I've submitted the request and someone will review it."
                ),
                audit_log_id=log_id, risk_level=spec.risk_level,
            )

        # --- 6. Execute ---------------------------------------------------
        try:
            data = spec.impl(self.db, params)
        except ToolExecutionError as exc:
            log_id = self._audit(
                tool_name=tool_name, params=params.model_dump(),
                risk_level=spec.risk_level,
                permission_result=PermissionResult.PASS,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.ERROR, error_message=str(exc),
            )
            return GovernanceResult(
                outcome=Outcome.ERROR, message=str(exc),
                audit_log_id=log_id, risk_level=spec.risk_level,
            )
        except Exception as exc:  # unexpected: log, never leak internals
            log_id = self._audit(
                tool_name=tool_name, params=params.model_dump(),
                risk_level=spec.risk_level,
                permission_result=PermissionResult.PASS,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                outcome=Outcome.ERROR,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            return GovernanceResult(
                outcome=Outcome.ERROR,
                message="Something went wrong on our side with that request.",
                audit_log_id=log_id, risk_level=spec.risk_level,
            )

        log_id = self._audit(
            tool_name=tool_name, params=params.model_dump(),
            risk_level=spec.risk_level,
            permission_result=PermissionResult.PASS,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            outcome=Outcome.EXECUTED, error_message=None,
        )
        return GovernanceResult(
            outcome=Outcome.EXECUTED, message="ok", data=data,
            audit_log_id=log_id, risk_level=spec.risk_level,
        )
