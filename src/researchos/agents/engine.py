"""ResearchOS AI — Deterministic Finite State Machine (FSM) Agent Orchestrator."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from researchos.core.exceptions import ApprovalRequiredError, StateTransitionError
from researchos.core.logging import get_logger
from researchos.core.security import ApprovalTokenManager, RiskTier
from researchos.memory.db import DatabaseManager

logger = get_logger("agents.engine")


class AgentState(str, Enum):
    """Deterministic states of the Central Agent Brain."""

    INITIALIZING = "INITIALIZING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Valid deterministic state transitions graph
VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.INITIALIZING: {AgentState.ANALYZING, AgentState.FAILED},
    AgentState.ANALYZING: {AgentState.PLANNING, AgentState.FAILED},
    AgentState.PLANNING: {AgentState.AWAITING_APPROVAL, AgentState.EXECUTING, AgentState.FAILED},
    AgentState.AWAITING_APPROVAL: {AgentState.EXECUTING, AgentState.PLANNING, AgentState.FAILED},
    AgentState.EXECUTING: {AgentState.VERIFYING, AgentState.FAILED},
    AgentState.VERIFYING: {AgentState.COMPLETED, AgentState.PLANNING, AgentState.FAILED},
    AgentState.COMPLETED: set(),  # Terminal state
    AgentState.FAILED: {AgentState.INITIALIZING},  # Terminal unless explicitly reset
}


class TaskStep(BaseModel):
    """Discrete step within a task execution plan."""

    step_index: int
    description: str
    risk_tier: RiskTier = RiskTier.READ_ONLY
    requires_approval: bool = False
    status: str = "PENDING"
    output: Any = None


class StateTransitionRecord(BaseModel):
    """Immutable audit record of a state transition."""

    from_state: AgentState
    to_state: AgentState
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str
    approval_token: str | None = None


class DeterministicAgentEngine:
    """
    Deterministic Finite State Machine (FSM) managing task lifecycles,
    Human-in-the-Loop approval gates, and verification loops.
    """

    def __init__(
        self,
        task_id: str,
        db_manager: DatabaseManager | None = None,
        token_manager: ApprovalTokenManager | None = None,
    ) -> None:
        self.task_id = task_id
        self.db = db_manager
        self.token_manager = token_manager or ApprovalTokenManager()
        self.current_state: AgentState = AgentState.INITIALIZING
        self.history: list[StateTransitionRecord] = []
        self.plan: list[TaskStep] = []
        self.context: dict[str, Any] = {}

    def transition_to(
        self,
        target_state: AgentState,
        reason: str,
        approval_token: str | None = None,
    ) -> StateTransitionRecord:
        """
        Transitions the engine to a new state if valid under the FSM graph.
        Enforces human approval gates for consequential operations.
        """
        allowed = VALID_TRANSITIONS.get(self.current_state, set())
        if target_state not in allowed:
            raise StateTransitionError(
                f"Illegal state transition: Cannot transition from {self.current_state.value} "
                f"to {target_state.value}. Allowed: {[s.value for s in allowed]}"
            )

        # Approval gate enforcement: transitioning from AWAITING_APPROVAL to EXECUTING
        # requires a valid, non-expired, unconsumed approval token.
        if (
            self.current_state == AgentState.AWAITING_APPROVAL
            and target_state == AgentState.EXECUTING
        ):
            if not approval_token:
                raise ApprovalRequiredError(
                    f"Execution blocked: Task {self.task_id} requires explicit human approval token to execute."
                )
            self.token_manager.validate_and_consume_token(
                approval_token,
                expected_action=f"execute_task:{self.task_id}",
                expected_target=self.task_id,
            )

        record = StateTransitionRecord(
            from_state=self.current_state,
            to_state=target_state,
            reason=reason,
            approval_token=approval_token,
        )

        previous_state = self.current_state
        self.current_state = target_state
        self.history.append(record)

        # Commit to audit log if database manager is configured
        if self.db:
            try:
                self.db.log_audit_event(
                    action=f"fsm_transition:{previous_state.value}->{target_state.value}",
                    target=f"task:{self.task_id}",
                    user_approved=bool(approval_token),
                    approval_token=approval_token,
                    details={"reason": reason, "step_count": len(self.plan)},
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to record audit event for state transition: {e}")

        logger.info(
            f"FSM [{self.task_id}] transitioned {previous_state.value} -> {target_state.value}: {reason}"
        )
        return record

    def set_plan(self, steps: list[TaskStep]) -> None:
        """Sets the execution plan and flags whether human approval is mandated."""
        self.plan = steps
        # If any step is consequential, flag it
        for step in self.plan:
            if step.risk_tier == RiskTier.CONSEQUENTIAL_EXECUTION:
                step.requires_approval = True

    def requires_human_approval(self) -> bool:
        """Returns True if any pending step in the plan requires human approval."""
        return any(step.requires_approval and step.status == "PENDING" for step in self.plan)

    def evaluate_plan_route(self) -> AgentState:
        """Determines next state from PLANNING based on risk tiers of planned steps."""
        if self.current_state != AgentState.PLANNING:
            raise StateTransitionError("Can only evaluate plan routing from PLANNING state.")

        if self.requires_human_approval():
            return self.transition_to(
                AgentState.AWAITING_APPROVAL,
                reason="Task plan contains consequential operations requiring human approval.",
            ).to_state
        else:
            return self.transition_to(
                AgentState.EXECUTING,
                reason="Task plan contains only autonomous read-only or low-risk operations.",
            ).to_state
