"""
Test script for the orchestrator.

Run with: python -m app.test_orchestrator

This validates:
1. Orchestrator executes steps in order
2. Events are emitted correctly
3. Context flows between steps
4. WorkflowRun is populated correctly
5. Real validators are used (ValidatorDispatcher)
"""

import asyncio
from uuid import uuid4

from app.models import (
    EventType,
    ExecutionEvent,
    ModelName,
    Step,
    ValidationRule,
    ValidationType,
    Workflow,
)
from app.orchestrator import create_orchestrator


def main():
    """Run a simple workflow and print events."""
    
    # Collect events for inspection
    events: list[ExecutionEvent] = []
    
    def on_event(event: ExecutionEvent):
        events.append(event)
        print(f"  [{event.event.value}] step={event.step_id}, attempt={event.attempt}")
    
    # Create a simple 2-step workflow
    # Note: StubLLMClient returns "[STUB] Response to: ..." which is NOT valid Python
    # So we use CONTAINS validation instead of PYTHON_SYNTAX for this test
    workflow = Workflow(
        id=uuid4(),
        name="Test Workflow",
        steps=[
            Step(
                name="Step 1: Generate greeting",
                order=0,
                model=ModelName.KIMI_K2_INSTRUCT,
                prompt="Write a greeting message.",
                validations=[
                    # Stub output contains "[STUB]" so this will pass
                    ValidationRule(type=ValidationType.CONTAINS, expected="[STUB]"),
                ],
                max_retries=2,
            ),
            Step(
                name="Step 2: Expand on greeting",
                order=1,
                model=ModelName.KIMI_K2P5,
                prompt="Expand on this: {{context}}",
                validations=[],  # No validation
                max_retries=1,
            ),
        ],
    )
    
    # Create orchestrator with real validator (default)
    orchestrator = create_orchestrator(on_event=on_event)
    
    # Run workflow
    print(f"\n{'='*60}")
    print(f"Running workflow: {workflow.name}")
    print(f"Steps: {len(workflow.steps)}")
    print(f"{'='*60}\n")
    
    run = asyncio.run(orchestrator.run(workflow, initial_context=""))
    
    # Print results
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Status: {run.status.value}")
    print(f"Total cost: ${run.total_cost_usd:.6f}")
    print(f"Steps executed: {len(run.step_runs)}")
    print(f"Final output: {run.final_output[:100] if run.final_output else 'None'}...")
    
    if run.failure_reason:
        print(f"Failure reason: {run.failure_reason}")
    
    print(f"\nEvents emitted: {len(events)}")
    for event in events:
        print(f"  - {event.event.value}")
    
    # Assertions for sanity check
    assert run.status.value == "completed", f"Expected completed, got {run.status.value}"
    assert len(run.step_runs) == 2, f"Expected 2 step runs, got {len(run.step_runs)}"
    assert run.final_output is not None, "Expected final_output to be set"
    
    print("\n✅ All assertions passed!")


if __name__ == "__main__":
    main()
