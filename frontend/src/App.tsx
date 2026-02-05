/**
 * App.tsx - Main Agentic Workflow Builder Application
 * 
 * Architecture:
 * - Left sidebar: List of saved workflows
 * - Right panel: Workflow editor + Execution viewer
 * 
 * State Management:
 * - workflows: All saved workflows from backend
 * - selectedWorkflow: Currently selected for editing/running
 * - draftWorkflow: In-progress edits (not yet saved)
 * - executionEvents: Live events from WebSocket during run
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import './App.css';
import { 
  Workflow, 
  Step, 
  ValidationRule, 
  ExecutionEvent, 
  ValidationType,
  RunStatus 
} from './types';
import { 
  listWorkflows, 
  createWorkflow, 
  runWorkflow, 
  createEventSocket 
} from './api';

// ============================================================================
// Type Definitions for Local State
// ============================================================================

interface DraftStep {
  order: number;
  name: string;
  prompt: string;  // Backend uses "prompt"
  model: 'kimi-k2-instruct-0905' | 'kimi-k2p5';
  validations: ValidationRule[];  // Backend uses "validations"
  max_retries: number;
}

interface DraftWorkflow {
  name: string;
  description: string;
  steps: DraftStep[];
}

// ============================================================================
// Helper Functions
// ============================================================================

function createEmptyStep(order: number): DraftStep {
  return {
    order,
    name: `Step ${order}`,
    prompt: '',
    model: 'kimi-k2-instruct-0905',
    validations: [],
    max_retries: 2,
  };
}

function createEmptyWorkflow(): DraftWorkflow {
  return {
    name: '',
    description: '',
    steps: [createEmptyStep(1)],
  };
}

// ============================================================================
// Main App Component
// ============================================================================

function App() {
  // Workflow list state
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor state
  const [draft, setDraft] = useState<DraftWorkflow>(createEmptyWorkflow());
  const [isEditing, setIsEditing] = useState(false);

  // Execution state
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  // ============================================================================
  // Load workflows on mount
  // ============================================================================

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoading(true);
      const data = await listWorkflows();
      setWorkflows(data);
      setError(null);
    } catch (err) {
      setError('Failed to load workflows');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // ============================================================================
  // Workflow Selection
  // ============================================================================

  const selectWorkflow = (workflow: Workflow) => {
    setSelectedId(workflow.id);
    // Convert to draft format for editing
    setDraft({
      name: workflow.name,
      description: workflow.description,
      steps: workflow.steps.map(s => ({
        order: s.order,
        name: s.name,
        prompt: s.prompt,
        model: s.model,
        validations: s.validations || [],
        max_retries: s.max_retries,
      })),
    });
    setIsEditing(false);
    // Clear execution state
    setRunId(null);
    setRunStatus(null);
    setEvents([]);
  };

  const startNewWorkflow = () => {
    setSelectedId(null);
    setDraft(createEmptyWorkflow());
    setIsEditing(true);
    setRunId(null);
    setRunStatus(null);
    setEvents([]);
  };

  // ============================================================================
  // Draft Editing
  // ============================================================================

  const updateDraftField = (field: keyof DraftWorkflow, value: string) => {
    setDraft(prev => ({ ...prev, [field]: value }));
    setIsEditing(true);
  };

  const updateStep = (index: number, updates: Partial<DraftStep>) => {
    setDraft(prev => ({
      ...prev,
      steps: prev.steps.map((s, i) => i === index ? { ...s, ...updates } : s),
    }));
    setIsEditing(true);
  };

  const addStep = () => {
    setDraft(prev => ({
      ...prev,
      steps: [...prev.steps, createEmptyStep(prev.steps.length + 1)],
    }));
    setIsEditing(true);
  };

  const removeStep = (index: number) => {
    setDraft(prev => ({
      ...prev,
      steps: prev.steps
        .filter((_, i) => i !== index)
        .map((s, i) => ({ ...s, order: i + 1 })), // Re-order
    }));
    setIsEditing(true);
  };

  // ============================================================================
  // Validation Rule Editing
  // ============================================================================

  const addValidation = (stepIndex: number) => {
    const newRule: ValidationRule = {
      type: 'contains',
      expected: '',
    };
    updateStep(stepIndex, {
      validations: [...draft.steps[stepIndex].validations, newRule],
    });
  };

  const updateValidation = (
    stepIndex: number, 
    ruleIndex: number, 
    updates: Partial<ValidationRule>
  ) => {
    const step = draft.steps[stepIndex];
    const newRules = step.validations.map((r, i) => 
      i === ruleIndex ? { ...r, ...updates } : r
    );
    updateStep(stepIndex, { validations: newRules });
  };

  const removeValidation = (stepIndex: number, ruleIndex: number) => {
    const step = draft.steps[stepIndex];
    updateStep(stepIndex, {
      validations: step.validations.filter((_, i) => i !== ruleIndex),
    });
  };

  // ============================================================================
  // Save Workflow
  // ============================================================================

  const saveWorkflow = async () => {
    if (!draft.name.trim()) {
      alert('Please enter a workflow name');
      return;
    }
    if (draft.steps.some(s => !s.prompt.trim())) {
      alert('All steps must have a prompt');
      return;
    }

    try {
      const saved = await createWorkflow({
        name: draft.name,
        description: draft.description,
        steps: draft.steps,
      });
      
      // Refresh list and select the new workflow
      await loadWorkflows();
      setSelectedId(saved.id);
      setIsEditing(false);
    } catch (err) {
      console.error('Failed to save workflow:', err);
      alert('Failed to save workflow');
    }
  };

  // ============================================================================
  // Run Workflow
  // ============================================================================

  const executeWorkflow = useCallback(async () => {
    if (!selectedId) return;

    // Close existing WebSocket
    if (wsRef.current) {
      wsRef.current.close();
    }

    try {
      // Start the run
      const response = await runWorkflow(selectedId);
      setRunId(response.run_id);
      setRunStatus('running');
      setEvents([]);

      // Connect WebSocket for live events
      const ws = createEventSocket(response.run_id, {
        onEvent: (event) => {
          setEvents(prev => [...prev, event]);
          
          // Update status based on event type
          if (event.event_type === 'run_completed') {
            setRunStatus('completed');
          } else if (event.event_type === 'run_failed') {
            setRunStatus('failed');
          }
        },
        onError: (err) => {
          console.error('WebSocket error:', err);
        },
        onClose: () => {
          console.log('WebSocket closed');
        },
      });

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to start workflow:', err);
      alert('Failed to start workflow execution');
    }
  }, [selectedId]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <h1>🤖 Agentic Workflow Builder</h1>
        <button className="btn-primary" onClick={startNewWorkflow}>
          + New Workflow
        </button>
      </header>

      <div className="main-layout">
        {/* Sidebar - Workflow List */}
        <aside className="sidebar">
          <h2>Workflows</h2>
          {loading ? (
            <div className="loading">
              <div className="spinner"></div>
              Loading...
            </div>
          ) : workflows.length === 0 ? (
            <div className="empty-state">
              <p>No workflows yet</p>
              <p>Create your first one!</p>
            </div>
          ) : (
            <div className="workflow-list">
              {workflows.map(wf => (
                <div
                  key={wf.id}
                  className={`workflow-item ${selectedId === wf.id ? 'selected' : ''}`}
                  onClick={() => selectWorkflow(wf)}
                >
                  <h3>{wf.name}</h3>
                  <p>{wf.steps.length} step{wf.steps.length !== 1 ? 's' : ''}</p>
                </div>
              ))}
            </div>
          )}
        </aside>

        {/* Main Content */}
        <main className="main-content">
          {/* Workflow Editor Panel */}
          <section className="panel">
            <h2>
              {selectedId ? '✏️ Edit Workflow' : '🆕 New Workflow'}
              {isEditing && <span style={{ color: '#f59e0b', marginLeft: 10 }}>• unsaved</span>}
            </h2>

            {/* Workflow Metadata */}
            <div className="form-row">
              <div className="form-group">
                <label>Workflow Name</label>
                <input
                  type="text"
                  value={draft.name}
                  onChange={e => updateDraftField('name', e.target.value)}
                  placeholder="e.g., Code Generator Pipeline"
                />
              </div>
              <div className="form-group">
                <label>Description</label>
                <input
                  type="text"
                  value={draft.description}
                  onChange={e => updateDraftField('description', e.target.value)}
                  placeholder="Brief description..."
                />
              </div>
            </div>

            {/* Steps Editor */}
            <h3 style={{ marginTop: 20, marginBottom: 15 }}>Steps</h3>
            <div className="steps-list">
              {draft.steps.map((step, stepIdx) => (
                <StepEditor
                  key={stepIdx}
                  step={step}
                  stepIndex={stepIdx}
                  onUpdate={(updates) => updateStep(stepIdx, updates)}
                  onRemove={() => removeStep(stepIdx)}
                  onAddValidation={() => addValidation(stepIdx)}
                  onUpdateValidation={(ruleIdx, updates) => 
                    updateValidation(stepIdx, ruleIdx, updates)
                  }
                  onRemoveValidation={(ruleIdx) => 
                    removeValidation(stepIdx, ruleIdx)
                  }
                  canRemove={draft.steps.length > 1}
                />
              ))}
            </div>

            {/* Action Buttons */}
            <div className="button-row">
              <button className="btn-secondary" onClick={addStep}>
                + Add Step
              </button>
              <button className="btn-success" onClick={saveWorkflow}>
                💾 Save Workflow
              </button>
              {selectedId && (
                <button 
                  className="btn-primary" 
                  onClick={executeWorkflow}
                  disabled={runStatus === 'running'}
                >
                  ▶️ Run Workflow
                </button>
              )}
            </div>
          </section>

          {/* Execution Panel */}
          {(runId || events.length > 0) && (
            <section className={`panel execution-panel ${runStatus || ''}`}>
              <h2>
                📊 Execution
                {runStatus && (
                  <span className={`status-badge ${runStatus}`}>
                    {runStatus}
                  </span>
                )}
              </h2>
              <ExecutionViewer events={events} />
            </section>
          )}
        </main>
      </div>

      {error && (
        <div style={{ 
          position: 'fixed', 
          bottom: 20, 
          right: 20, 
          background: '#ef4444', 
          padding: '10px 20px',
          borderRadius: 8,
        }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// StepEditor Component
// ============================================================================

interface StepEditorProps {
  step: DraftStep;
  stepIndex: number;
  onUpdate: (updates: Partial<DraftStep>) => void;
  onRemove: () => void;
  onAddValidation: () => void;
  onUpdateValidation: (ruleIndex: number, updates: Partial<ValidationRule>) => void;
  onRemoveValidation: (ruleIndex: number) => void;
  canRemove: boolean;
}

function StepEditor({
  step,
  stepIndex,
  onUpdate,
  onRemove,
  onAddValidation,
  onUpdateValidation,
  onRemoveValidation,
  canRemove,
}: StepEditorProps) {
  return (
    <div className="step-card">
      <div className="step-header">
        <h3>
          <span className="step-number">{step.order}</span>
          <input
            type="text"
            value={step.name}
            onChange={e => onUpdate({ name: e.target.value })}
            style={{ 
              background: 'transparent', 
              border: 'none', 
              color: '#3b82f6',
              fontSize: '0.95rem',
              width: 200,
            }}
          />
        </h3>
        {canRemove && (
          <button className="btn-danger btn-small" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>

      <div className="form-group">
        <label>Prompt (use {"{{context}}"} for previous outputs)</label>
        <textarea
          value={step.prompt}
          onChange={e => onUpdate({ prompt: e.target.value })}
          placeholder="Enter the prompt for this step..."
          rows={3}
        />
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>Model</label>
          <select
            value={step.model}
            onChange={e => onUpdate({ model: e.target.value as DraftStep['model'] })}
          >
            <option value="kimi-k2-instruct-0905">kimi-k2-instruct-0905 (fast)</option>
            <option value="kimi-k2p5">kimi-k2p5 (advanced)</option>
          </select>
        </div>
        <div className="form-group">
          <label>Max Retries</label>
          <input
            type="number"
            min={0}
            max={5}
            value={step.max_retries}
            onChange={e => onUpdate({ max_retries: parseInt(e.target.value) || 0 })}
          />
        </div>
      </div>

      {/* Validation Rules */}
      <div style={{ marginTop: 15 }}>
        <label>Validation Rules</label>
        <div className="validation-list">
          {step.validations.map((rule, ruleIdx) => (
            <ValidationEditor
              key={ruleIdx}
              rule={rule}
              onUpdate={(updates) => onUpdateValidation(ruleIdx, updates)}
              onRemove={() => onRemoveValidation(ruleIdx)}
            />
          ))}
        </div>
        <button 
          className="btn-secondary btn-small" 
          onClick={onAddValidation}
          style={{ marginTop: 10 }}
        >
          + Add Validation
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// ValidationEditor Component
// ============================================================================

interface ValidationEditorProps {
  rule: ValidationRule;
  onUpdate: (updates: Partial<ValidationRule>) => void;
  onRemove: () => void;
}

function ValidationEditor({ rule, onUpdate, onRemove }: ValidationEditorProps) {
  const validationTypes: ValidationType[] = [
    'python_syntax',
    'json_valid', 
    'contains',
    'regex_match',
    'test_exec',
    'llm_judge',
  ];

  const handleTypeChange = (newType: ValidationType) => {
    // Set appropriate default fields for each type
    const updates: Partial<ValidationRule> = { type: newType };
    switch (newType) {
      case 'contains':
        updates.expected = '';
        break;
      case 'regex_match':
        updates.pattern = '';
        break;
      case 'test_exec':
        updates.test_code = '';
        break;
      case 'llm_judge':
        updates.criteria = '';
        break;
    }
    onUpdate(updates);
  };

  const getConfigInput = () => {
    switch (rule.type) {
      case 'contains':
        return (
          <input
            type="text"
            placeholder="Substring to find"
            value={rule.expected || ''}
            onChange={e => onUpdate({ expected: e.target.value })}
          />
        );
      case 'regex_match':
        return (
          <input
            type="text"
            placeholder="Regex pattern"
            value={rule.pattern || ''}
            onChange={e => onUpdate({ pattern: e.target.value })}
          />
        );
      case 'test_exec':
        return (
          <input
            type="text"
            placeholder="Test code (use 'output' variable)"
            value={rule.test_code || ''}
            onChange={e => onUpdate({ test_code: e.target.value })}
          />
        );
      case 'llm_judge':
        return (
          <input
            type="text"
            placeholder="Judgment criteria"
            value={rule.criteria || ''}
            onChange={e => onUpdate({ criteria: e.target.value })}
          />
        );
      default:
        return <span style={{ color: '#64748b' }}>No config needed</span>;
    }
  };

  return (
    <div className="validation-item">
      <select
        value={rule.type}
        onChange={e => handleTypeChange(e.target.value as ValidationType)}
      >
        {validationTypes.map(t => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      {getConfigInput()}
      <button className="btn-danger btn-small" onClick={onRemove}>×</button>
    </div>
  );
}

// ============================================================================
// ExecutionViewer Component
// ============================================================================

interface ExecutionViewerProps {
  events: ExecutionEvent[];
}

function ExecutionViewer({ events }: ExecutionViewerProps) {
  const logRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events]);

  if (events.length === 0) {
    return (
      <div className="empty-state">
        <p>Waiting for events...</p>
      </div>
    );
  }

  const formatPayload = (payload: Record<string, unknown> | undefined): string => {
    // Guard against undefined/null payload
    if (!payload || typeof payload !== 'object') {
      return '';
    }
    const keys = Object.keys(payload);
    if (keys.length === 0) return '';
    
    const key = keys[0];
    const value = payload[key];
    if (typeof value === 'string' && value.length > 100) {
      return `${key}: ${value.substring(0, 100)}...`;
    }
    return JSON.stringify(payload);
  };

  return (
    <div className="event-log" ref={logRef}>
      {events.map((event, idx) => (
        <div key={idx} className="event-item">
          <span className={`event-type ${event.event_type}`}>
            {event.event_type}
          </span>
          <span className="event-payload">
            {formatPayload(event.payload)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default App;
