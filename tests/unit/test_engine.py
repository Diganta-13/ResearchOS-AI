"""Unit tests for deterministic FSM agent orchestrator."""

import pytest

from researchos.agents.engine import AgentState, DeterministicAgentEngine, TaskStep
from researchos.core.exceptions import ApprovalRequiredError, StateTransitionError
from researchos.core.security import ApprovalTokenManager, RiskTier
from researchos.memory.db import DatabaseManager


def test_fsm_valid_lifecycle(isolated_db: DatabaseManager):
    engine = DeterministicAgentEngine(task_id="task_1", db_manager=isolated_db)
    assert engine.current_state == AgentState.INITIALIZING

    engine.transition_to(AgentState.ANALYZING, reason="Requirement parsed")
    assert engine.current_state == AgentState.ANALYZING

    engine.transition_to(AgentState.PLANNING, reason="Architecture designed")
    assert engine.current_state == AgentState.PLANNING

    # Set plan with read-only steps
    engine.set_plan([TaskStep(step_index=1, description="Read doc", risk_tier=RiskTier.READ_ONLY)])
    next_state = engine.evaluate_plan_route()
    assert next_state == AgentState.EXECUTING
    assert engine.current_state == AgentState.EXECUTING

    engine.transition_to(AgentState.VERIFYING, reason="Execution complete")
    assert engine.current_state == AgentState.VERIFYING

    engine.transition_to(AgentState.COMPLETED, reason="Post-conditions satisfied")
    assert engine.current_state == AgentState.COMPLETED


def test_fsm_illegal_transition(isolated_db: DatabaseManager):
    engine = DeterministicAgentEngine(task_id="task_bad", db_manager=isolated_db)
    # Cannot jump directly from INITIALIZING to EXECUTING
    with pytest.raises(StateTransitionError) as exc_info:
        engine.transition_to(AgentState.EXECUTING, reason="Illegal jump")
    assert "Illegal state transition" in str(exc_info.value)


def test_fsm_consequential_approval_gate(isolated_db: DatabaseManager):
    token_mgr = ApprovalTokenManager(secret_key="test-secret")
    engine = DeterministicAgentEngine(
        task_id="task_approval", db_manager=isolated_db, token_manager=token_mgr
    )

    engine.transition_to(AgentState.ANALYZING, reason="Analyze")
    engine.transition_to(AgentState.PLANNING, reason="Plan")

    # Set plan containing a consequential step
    engine.set_plan(
        [
            TaskStep(
                step_index=1, description="Delete file", risk_tier=RiskTier.CONSEQUENTIAL_EXECUTION
            )
        ]
    )
    assert engine.requires_human_approval() is True

    # Routing from planning must route to AWAITING_APPROVAL
    next_state = engine.evaluate_plan_route()
    assert next_state == AgentState.AWAITING_APPROVAL
    assert engine.current_state == AgentState.AWAITING_APPROVAL

    # Transitioning to EXECUTING without token fails
    with pytest.raises(ApprovalRequiredError):
        engine.transition_to(AgentState.EXECUTING, reason="Attempt run without token")

    # Transitioning with valid token succeeds
    token = token_mgr.generate_token(action="execute_task:task_approval", target="task_approval")
    engine.transition_to(AgentState.EXECUTING, reason="Approved by user", approval_token=token)
    assert engine.current_state == AgentState.EXECUTING
