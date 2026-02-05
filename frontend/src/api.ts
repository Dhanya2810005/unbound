/**
 * API client for the workflow backend.
 * 
 * WHY separate file:
 * - Single source of truth for API calls
 * - Easy to mock for testing
 * - Centralized error handling
 */

import { 
  Workflow, 
  CreateWorkflowRequest, 
  WorkflowRun, 
  RunWorkflowResponse,
  ExecutionEvent 
} from './types';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

/**
 * Generic fetch wrapper with error handling.
 */
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API error (${response.status}): ${error}`);
  }

  return response.json();
}

// =============================================================================
// WORKFLOW CRUD
// =============================================================================

export async function createWorkflow(data: CreateWorkflowRequest): Promise<Workflow> {
  return apiFetch<Workflow>('/workflows', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function listWorkflows(): Promise<Workflow[]> {
  return apiFetch<Workflow[]>('/workflows');
}

export async function getWorkflow(id: string): Promise<Workflow> {
  return apiFetch<Workflow>(`/workflows/${id}`);
}

export async function updateWorkflow(id: string, data: Partial<CreateWorkflowRequest>): Promise<Workflow> {
  return apiFetch<Workflow>(`/workflows/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteWorkflow(id: string): Promise<void> {
  await apiFetch(`/workflows/${id}`, { method: 'DELETE' });
}

// =============================================================================
// WORKFLOW EXECUTION
// =============================================================================

export async function runWorkflow(
  workflowId: string,
  initialContext: string = ''
): Promise<RunWorkflowResponse> {
  return apiFetch<RunWorkflowResponse>(`/workflows/${workflowId}/run`, {
    method: 'POST',
    body: JSON.stringify({ initial_context: initialContext }),
  });
}

export async function getRunStatus(runId: string): Promise<WorkflowRun> {
  return apiFetch<WorkflowRun>(`/runs/${runId}`);
}

export async function listRuns(): Promise<WorkflowRun[]> {
  return apiFetch<WorkflowRun[]>('/runs');
}

// =============================================================================
// WEBSOCKET
// =============================================================================

interface EventSocketOptions {
  onEvent: (event: ExecutionEvent) => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
}

export function createEventSocket(
  runId: string,
  options: EventSocketOptions
): WebSocket {
  const wsBase = API_BASE.replace('http', 'ws');
  const ws = new WebSocket(`${wsBase}/runs/${runId}/events`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as ExecutionEvent;
      options.onEvent(data);
    } catch (e) {
      console.error('Failed to parse WebSocket message:', e);
    }
  };

  ws.onclose = () => {
    options.onClose?.();
  };

  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
    options.onError?.(error);
  };

  return ws;
}
