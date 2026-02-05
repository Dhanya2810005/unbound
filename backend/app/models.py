"""
Pydantic data models for the Agentic Workflow Builder.

These models define the contracts that ALL components depend on:
- API request/response shapes
- Database row mappings (via SQLAlchemy later)
- WebSocket event payloads
- Orchestrator internal state

Design principles:
1. Immutable where possible (frozen=True for value objects)
2. Explicit enums over magic strings
3. Optional fields have sensible defaults
4. Models are JSON-serializable for easy WebSocket/export
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ENUMS — Explicit states prevent typos and enable IDE autocomplete

class ValidationType(str, Enum):
    """
    Supported validation strategies.
    
    WHY str, Enum: Inheriting from str makes JSON serialization automatic.
    The orchestrator uses this to dispatch to the correct validator.
    """
    PYTHON_SYNTAX = "python_syntax"     # ast.parse() check
    JSON_VALID = "json_valid"           # json.loads() check
    REGEX_MATCH = "regex_match"         # re.search() against pattern
    CONTAINS = "contains"               # substring check
    TEST_EXEC = "test_exec"             # safe exec with assertions
    LLM_JUDGE = "llm_judge"             # LLM returns YES/NO only


class StepStatus(str, Enum):
    """Status of a single step execution."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"  # If workflow aborts early


class RunStatus(str, Enum):
    """Status of an entire workflow run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
    """
    WebSocket event types.
    
    WHY explicit enum: Frontend can switch on event type safely.
    Adding a new event type forces you to handle it everywhere.
    """
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    LLM_CHUNK = "llm_chunk"             # For streaming tokens (future)
    LLM_OUTPUT = "llm_output"           # Full LLM response
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class ModelName(str, Enum):
    """
    Available LLM models via Unbound API.
    
    WHY enum: Prevents typos, documents available options,
    and makes cost calculation straightforward.
    """
    KIMI_K2_INSTRUCT = "kimi-k2-instruct-0905"  # Structured tasks, code
    KIMI_K2P5 = "kimi-k2p5"                      # Explanations, summaries


# VALIDATION RULE — Defines how to check LLM output

class ValidationRule(BaseModel):
    """
    A single validation check applied to step output.
    
    WHY separate model: Steps can have multiple validations.
    Each validation is independent and can fail/pass individually.
    
    Examples:
        - {"type": "python_syntax"} 
        - {"type": "regex_match", "pattern": "^def \\w+"}
        - {"type": "llm_judge", "criteria": "Is this valid Python?"}
    """
    type: ValidationType
    pattern: Optional[str] = None       # For regex_match
    expected: Optional[str] = None      # For contains
    criteria: Optional[str] = None      # For llm_judge (the question to ask)
    test_code: Optional[str] = None     # For test_exec (assertions to run)

    class Config:
        frozen = True  # Validation rules are immutable value objects


# STEP — A single unit of work in a workflow

class Step(BaseModel):
    """
    One step in a workflow.
    
    WHY this structure:
    - `id` is client-generated (UUID) for idempotency
    - `order` is explicit (not inferred from list position) for robustness
    - `prompt` is a template; orchestrator injects {{context}} at runtime
    - `validations` is a list because multiple checks are common
    - `max_retries` defaults to 2 (3 total attempts) — hackathon-safe
    
    The orchestrator will:
    1. Build final prompt with context
    2. Call LLM
    3. Run all validations
    4. Retry up to max_retries if any validation fails
    """
    id: UUID = Field(default_factory=uuid4)
    name: str                           # Human-readable label
    order: int                          # Execution order (0-indexed)
    model: ModelName                    # Which LLM to use
    prompt: str                         # Prompt template (may include {{context}})
    system_prompt: Optional[str] = None # Optional system message
    validations: list[ValidationRule] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0, le=5)  # Cap at 5 to prevent runaway

    class Config:
        frozen = True



# WORKFLOW — A sequence of steps


class Workflow(BaseModel):
    """
    A complete workflow definition.
    
    WHY this structure:
    - `id` is UUID for database primary key
    - `name` is for display in UI
    - `steps` are stored as a list; `order` field handles sequencing
    - `created_at` / `updated_at` for audit trail
    - `webhook_url` (optional) for completion notifications
    
    The workflow is a TEMPLATE — executing it creates a WorkflowRun.
    """
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None
    steps: list[Step] = Field(default_factory=list)
    webhook_url: Optional[str] = None   # Called on completion/failure
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)



# STEP RUN — Execution record for a single step


class StepRun(BaseModel):
    """
    Records the execution of one step in a workflow run.
    
    WHY this structure:
    - `step_id` links back to the Step definition
    - `attempt` tracks retry count (1 = first try)
    - `input_context` captures what was passed in (for debugging)
    - `output` stores raw LLM response
    - `cost` is approximate token-based cost (for tracking)
    - `error` captures failure reason if status == FAILED
    
    Multiple StepRun records may exist for one step (one per retry attempt).
    """
    id: UUID = Field(default_factory=uuid4)
    step_id: UUID
    attempt: int = 1
    status: StepStatus = StepStatus.PENDING
    input_context: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0               # Approximate cost
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# WORKFLOW RUN — Execution record for an entire workflow


class WorkflowRun(BaseModel):
    """
    Records the execution of a complete workflow.
    
    WHY this structure:
    - `workflow_id` links to the Workflow template
    - `status` tracks overall progress
    - `step_runs` is a dict keyed by step_id (UUID) for O(1) lookup
    - `context` accumulates outputs from each step (passed to next step)
    - `total_cost_usd` aggregates all step costs
    - `final_output` stores the last step's output for easy access
    - `failure_reason` captures why the workflow failed (if applicable)
    
    The orchestrator creates one WorkflowRun per execution and updates it
    as steps complete. This is the source of truth for execution state.
    """
    id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    status: RunStatus = RunStatus.PENDING
    # Tracks the `order` value of the current step being executed (not array index)
    current_step_order: int = 0
    step_runs: dict[UUID, StepRun] = Field(default_factory=dict)  # step_id -> StepRun
    context: str = ""                   # Accumulated context passed between steps
    final_output: Optional[str] = None  # Last step's output for frontend display
    failure_reason: Optional[str] = None  # e.g., "Step 3 failed: SyntaxError"
    total_cost_usd: float = 0.0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# EXECUTION EVENT — WebSocket message payload

class ExecutionEvent(BaseModel):
    """
    Event emitted to WebSocket during workflow execution.
    
    WHY this structure:
    - `event` is the discriminator (frontend switches on this)
    - `run_id` + `step_id` identify context
    - `attempt` shows which retry this is
    - `timestamp` enables timeline reconstruction
    - `payload` is flexible (dict) for event-specific data
    
    Examples:
        {"event": "step_started", "step_id": "...", "attempt": 1, "payload": {}}
        {"event": "llm_output", "payload": {"output": "def foo(): ..."}}
        {"event": "validation_failed", "payload": {"reason": "SyntaxError"}}
    
    The frontend is DUMB — it just renders events in order.
    """
    event: EventType
    run_id: UUID
    step_id: Optional[UUID] = None
    attempt: int = 1
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)

    class Config:
        # Allow UUID serialization to string for JSON
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat()
        }


# API REQUEST/RESPONSE MODELS — For FastAPI endpoints

class WorkflowCreate(BaseModel):
    """Request body for creating a workflow."""
    name: str
    description: Optional[str] = None
    steps: list[Step] = Field(default_factory=list)
    webhook_url: Optional[str] = None


class WorkflowUpdate(BaseModel):
    """Request body for updating a workflow."""
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[list[Step]] = None
    webhook_url: Optional[str] = None


class RunWorkflowRequest(BaseModel):
    """Request body to start a workflow execution."""
    initial_context: str = ""           # Optional starting context


class RunWorkflowResponse(BaseModel):
    """Response when starting a workflow run."""
    run_id: UUID
    websocket_url: str                  # Where to connect for live updates
