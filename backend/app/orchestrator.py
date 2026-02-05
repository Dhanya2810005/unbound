"""
Orchestrator: The core execution engine for workflows.

This module is responsible for:
1. Executing workflow steps sequentially (by Step.order)
2. Managing retries per step
3. Accumulating context between steps
4. Emitting events for real-time UI updates
5. Tracking execution state in WorkflowRun

DESIGN PRINCIPLES:
- Pure Python logic — no FastAPI, no I/O, no side effects except via callbacks
- LLM calls and validation are abstracted behind interfaces (dependency injection)
- Events are emitted via a callback, not directly to WebSocket
- The orchestrator is AUTHORITATIVE: it decides pass/fail, not the LLM

WHY THIS STRUCTURE:
- Testable: inject mock LLM client and validators
- Readable: main loop is simple, helpers handle details
- Extensible: swap LLM provider or add validators without touching core logic
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Protocol
from uuid import UUID

from .models import (
    EventType,
    ExecutionEvent,
    ModelName,
    RunStatus,
    Step,
    StepRun,
    StepStatus,
    ValidationRule,
    Workflow,
    WorkflowRun,
)

@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    async def call(
        self,
        model: ModelName,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        ...


@dataclass
class ValidationResult:
    passed: bool
    error: Optional[str] = None


class Validator(Protocol):
    async def validate(
        self,
        output: str,
        rule: ValidationRule,
        llm_client: Optional[LLMClient] = None, 
    ) -> ValidationResult:
        ...


EventCallback = Callable[[ExecutionEvent], None]


# =============================================================================
# STUB IMPLEMENTATIONS — Replace with real ones later
# =============================================================================

class StubLLMClient:
    async def call(
        self,
        model: ModelName,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        # Simulate a simple response
        return LLMResponse(
            content=f"[STUB] Response to: {prompt[:50]}...",
            prompt_tokens=len(prompt.split()),
            completion_tokens=10,
        )


class StubValidator:
    """
    Placeholder validator that always passes.
    
    WHY: Allows testing orchestrator retry/success logic.
    Replace with real dispatcher later.
    """
    async def validate(
        self,
        output: str,
        rule: ValidationRule,
        llm_client: Optional[LLMClient] = None,
    ) -> ValidationResult:
        # Always pass for now
        return ValidationResult(passed=True)


# =============================================================================
# ORCHESTRATOR — Main execution engine
# =============================================================================

class Orchestrator:
    """
    Executes workflows step-by-step with retry logic.
    
    FLOW:
    1. Sort steps by order
    2. For each step:
       a. Build prompt with context
       b. Call LLM
       c. Run all validations
       d. If all pass → update context, move to next step
       e. If any fail → retry up to max_retries
       f. If retries exhausted → fail workflow
    3. Emit events at each significant point
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        validator: Validator,
        on_event: Optional[EventCallback] = None,
    ):
        self.llm_client = llm_client
        self.validator = validator
        self.on_event = on_event or (lambda e: None)  # No-op if not provided
    
    def _emit(
        self,
        event_type: EventType,
        run: WorkflowRun,
        step: Optional[Step] = None,
        attempt: int = 1,
        payload: Optional[dict] = None,
    ) -> None:
        event = ExecutionEvent(
            event=event_type,
            run_id=run.id,
            step_id=step.id if step else None,
            attempt=attempt,
            payload=payload or {},
        )
        self.on_event(event)
    
    def _build_prompt(self, step: Step, context: str) -> str:
        return step.prompt.replace("{{context}}", context)
    
    async def _execute_step(
        self,
        step: Step,
        run: WorkflowRun,
        context: str,
    ) -> tuple[StepRun, bool, str]:
        max_attempts = step.max_retries + 1  # max_retries=2 means 3 attempts
        
        for attempt in range(1, max_attempts + 1):
            # Create a new StepRun for this attempt
            step_run = StepRun(
                step_id=step.id,
                attempt=attempt,
                status=StepStatus.RUNNING,
                input_context=context,
                started_at=datetime.utcnow(),
            )
            
            # Emit step_started event
            self._emit(
                EventType.STEP_STARTED,
                run,
                step,
                attempt,
                {"step_name": step.name, "max_attempts": max_attempts},
            )
            
            # ─────────────────────────────────────────────────────────────
            # STEP 1: Call LLM
            # ─────────────────────────────────────────────────────────────
            try:
                final_prompt = self._build_prompt(step, context)
                llm_response = await self.llm_client.call(
                    model=step.model,
                    prompt=final_prompt,
                    system_prompt=step.system_prompt,
                )
                
                # Update step run with LLM output
                step_run.output = llm_response.content
                step_run.prompt_tokens = llm_response.prompt_tokens
                step_run.completion_tokens = llm_response.completion_tokens
                
                # Emit llm_output event
                self._emit(
                    EventType.LLM_OUTPUT,
                    run,
                    step,
                    attempt,
                    {"output": llm_response.content[:500]},
                )
                
            except Exception as e:
                step_run.status = StepStatus.FAILED
                step_run.error = f"LLM call failed: {str(e)}"
                step_run.finished_at = datetime.utcnow()
                
                self._emit(
                    EventType.VALIDATION_FAILED,
                    run,
                    step,
                    attempt,
                    {"reason": step_run.error},
                )
                
                if attempt < max_attempts:
                    continue  # Retry
                else:
                    return (step_run, False, context)  # All retries exhausted
            
            # ─────────────────────────────────────────────────────────────
            # STEP 2: Run all validations
            # ─────────────────────────────────────────────────────────────
            all_passed = True
            failed_reason = None
            
            for rule in step.validations:
                result = await self.validator.validate(
                    output=llm_response.content,
                    rule=rule,
                    llm_client=self.llm_client,  # For LLM_JUDGE
                )
                
                if not result.passed:
                    all_passed = False
                    failed_reason = result.error or f"Validation failed: {rule.type.value}"
                    break  # Stop on first failure
            
            # ─────────────────────────────────────────────────────────────
            # STEP 3: Handle validation result
            # ─────────────────────────────────────────────────────────────
            if all_passed:
                # SUCCESS — step passed
                step_run.status = StepStatus.PASSED
                step_run.finished_at = datetime.utcnow()
                
                self._emit(
                    EventType.VALIDATION_PASSED,
                    run,
                    step,
                    attempt,
                    {},
                )
                self._emit(
                    EventType.STEP_COMPLETED,
                    run,
                    step,
                    attempt,
                    {"output": llm_response.content[:500]},
                )
                
                # Return success with new context (LLM output becomes context)
                new_context = llm_response.content
                return (step_run, True, new_context)
            
            else:
                # FAILURE — validation failed
                step_run.status = StepStatus.FAILED
                step_run.error = failed_reason
                step_run.finished_at = datetime.utcnow()
                
                self._emit(
                    EventType.VALIDATION_FAILED,
                    run,
                    step,
                    attempt,
                    {"reason": failed_reason},
                )
                
                if attempt < max_attempts:
                    # Retry — emit will happen at top of next iteration
                    continue
                else:
                    # All retries exhausted
                    self._emit(
                        EventType.STEP_FAILED,
                        run,
                        step,
                        attempt,
                        {"reason": f"All {max_attempts} attempts failed"},
                    )
                    return (step_run, False, context)
        
        # Should never reach here, but satisfy type checker
        return (step_run, False, context)
    
    async def run(
        self,
        workflow: Workflow,
        initial_context: str = "",
        run_id: Optional[UUID] = None,
    ) -> WorkflowRun:
        # ─────────────────────────────────────────────────────────────────
        # INITIALIZE RUN
        # ─────────────────────────────────────────────────────────────────
        run = WorkflowRun(
            id=run_id,
            workflow_id=workflow.id,
            status=RunStatus.RUNNING,
            context=initial_context,
            started_at=datetime.utcnow(),
        )
        
        self._emit(
            EventType.RUN_STARTED,
            run,
            payload={"workflow_name": workflow.name, "step_count": len(workflow.steps)},
        )
        
        # ─────────────────────────────────────────────────────────────────
        # SORT STEPS BY ORDER
        # WHY: Steps may be stored out of order; order field is authoritative
        # ─────────────────────────────────────────────────────────────────
        sorted_steps = sorted(workflow.steps, key=lambda s: s.order)
        
        # ─────────────────────────────────────────────────────────────────
        # EXECUTE STEPS SEQUENTIALLY
        # ─────────────────────────────────────────────────────────────────
        current_context = initial_context
        
        for step in sorted_steps:
            run.current_step_order = step.order
            
            # Execute step (handles retries internally)
            step_run, success, new_context = await self._execute_step(
                step=step,
                run=run,
                context=current_context,
            )
            
            # Record step run (keyed by step UUID)
            run.step_runs[step.id] = step_run
            
            # Accumulate cost
            # WHY: Simple cost tracking — we'll estimate USD later
            run.total_cost_usd += self._estimate_cost(
                step_run.prompt_tokens,
                step_run.completion_tokens,
                step.model,
            )
            
            if success:
                # Update context for next step
                current_context = new_context
                run.context = current_context
            else:
                # Step failed permanently — abort workflow
                run.status = RunStatus.FAILED
                run.failure_reason = f"Step '{step.name}' failed: {step_run.error}"
                run.finished_at = datetime.utcnow()
                
                # Mark remaining steps as skipped
                for remaining_step in sorted_steps:
                    if remaining_step.order > step.order:
                        skipped_run = StepRun(
                            step_id=remaining_step.id,
                            status=StepStatus.SKIPPED,
                        )
                        run.step_runs[remaining_step.id] = skipped_run
                
                self._emit(
                    EventType.RUN_FAILED,
                    run,
                    payload={"reason": run.failure_reason},
                )
                
                return run
        
        # ─────────────────────────────────────────────────────────────────
        # ALL STEPS COMPLETED SUCCESSFULLY
        # ─────────────────────────────────────────────────────────────────
        run.status = RunStatus.COMPLETED
        run.final_output = current_context  # Last step's output
        run.finished_at = datetime.utcnow()
        
        self._emit(
            EventType.RUN_COMPLETED,
            run,
            payload={"total_cost_usd": run.total_cost_usd},
        )
        
        return run
    
    def _estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: ModelName,
    ) -> float:
        rates = {
            ModelName.KIMI_K2_INSTRUCT: {"prompt": 0.001, "completion": 0.002},
            ModelName.KIMI_K2P5: {"prompt": 0.002, "completion": 0.004},
        }
        
        rate = rates.get(model, {"prompt": 0.001, "completion": 0.002})
        
        prompt_cost = (prompt_tokens / 1000) * rate["prompt"]
        completion_cost = (completion_tokens / 1000) * rate["completion"]
        
        return prompt_cost + completion_cost


# =============================================================================
# FACTORY FUNCTION — Convenience for creating orchestrator with defaults
# =============================================================================

def create_orchestrator(
    llm_client: Optional[LLMClient] = None,
    validator: Optional[Validator] = None,
    on_event: Optional[EventCallback] = None,
    use_real_validator: bool = True,
) -> Orchestrator:
    """
    Create an orchestrator with optional dependency injection.
    
    Args:
        llm_client: LLM implementation (defaults to StubLLMClient)
        validator: Validator implementation (defaults to ValidatorDispatcher)
        on_event: Callback for execution events
        use_real_validator: If True, uses ValidatorDispatcher; if False, uses stub
    
    WHY use_real_validator flag:
    - Default True: production behavior with real validation
    - Set False for testing orchestrator flow without validation failures
    """
    # Import here to avoid circular dependency
    from .validators import ValidatorDispatcher
    
    # Determine validator
    if validator is not None:
        actual_validator = validator
    elif use_real_validator:
        actual_validator = ValidatorDispatcher()
    else:
        actual_validator = StubValidator()
    
    return Orchestrator(
        llm_client=llm_client or StubLLMClient(),
        validator=actual_validator,
        on_event=on_event,
    )
