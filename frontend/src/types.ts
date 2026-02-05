/**
 * TypeScript types matching the backend Pydantic models.
 * 
 * WHY duplicate types:
 * - Type safety in frontend
 * - IDE autocomplete
 * - Catch mismatches at compile time
 */

// Validation types supported by the backend
// Backend enum values are lowercase strings
export type ValidationType = 
  | 'python_syntax'
  | 'json_valid'
  | 'regex_match'
  | 'contains'
  | 'test_exec'
  | 'llm_judge';

// Available LLM models
export type ModelName = 'kimi-k2-instruct-0905' | 'kimi-k2p5';

// Status enums
export type StepStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed';

// Event types from WebSocket
export type EventType = 
  | 'run_started'
  | 'step_started'
  | 'llm_chunk'
  | 'llm_output'
  | 'validation_passed'
  | 'validation_failed'
  | 'step_completed'
  | 'step_failed'
  | 'run_completed'
  | 'run_failed';

// Validation rule configuration
// Backend uses flat fields, not nested config
export interface ValidationRule {
  type: ValidationType;
  pattern?: string;       // For REGEX_MATCH
  expected?: string;      // For CONTAINS (backend field name)
  criteria?: string;      // For LLM_JUDGE
  test_code?: string;     // For TEST_EXEC
}

// A single step in a workflow
export interface Step {
  id: string;
  name: string;
  order: number;
  model: ModelName;
  prompt: string;           // Backend uses "prompt", not "prompt_template"
  system_prompt?: string;
  validations: ValidationRule[];  // Backend uses "validations", not "validation_rules"
  max_retries: number;
}

// Complete workflow definition
export interface Workflow {
  id: string;
  name: string;
  description: string;
  steps: Step[];
  created_at: string;
  updated_at: string;
}

// Request to create a workflow
export interface CreateWorkflowRequest {
  name: string;
  description?: string;
  steps: Array<{
    order: number;
    name: string;
    prompt: string;         // Backend uses "prompt"
    model: ModelName;
    validations: ValidationRule[];  // Backend uses "validations"
    max_retries: number;
  }>;
}

// Execution event from WebSocket
export interface ExecutionEvent {
  event_type: EventType;
  run_id: string;
  step_id?: string;
  attempt?: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

// Workflow run status
export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: RunStatus;
  current_step_order: number;
  context: string;
  final_output?: string;
  failure_reason?: string;
  total_cost_usd: number;
  started_at?: string;
  finished_at?: string;
}

// Response when starting a run
export interface RunWorkflowResponse {
  run_id: string;
  websocket_url: string;
}
