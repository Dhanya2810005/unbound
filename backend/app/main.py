"""
FastAPI application for the Agentic Workflow Builder.

This module wires together:
- REST API for workflow CRUD
- WebSocket for real-time execution events
- Orchestrator for workflow execution
- In-memory storage for hackathon simplicity

ARCHITECTURE:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   FastAPI   │────▶│ Orchestrator│
│  (React)    │◀────│   Backend   │◀────│             │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │
       │    WebSocket      │    Events callback
       └───────────────────┘
"""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ExecutionEvent,
    EventType,
    RunStatus,
    RunWorkflowRequest,
    RunWorkflowResponse,
    Workflow,
    WorkflowCreate,
    WorkflowRun,
    WorkflowUpdate,
)
from .orchestrator import Orchestrator, create_orchestrator
from .llm_client import create_unbound_client
from .validators import ValidatorDispatcher


workflows: dict[UUID, Workflow] = {}
workflow_runs: dict[UUID, WorkflowRun] = {}

websocket_connections: dict[UUID, list[WebSocket]] = {}

# Buffer events until WebSocket connects
pending_events: dict[UUID, list[ExecutionEvent]] = {}



app = FastAPI(
    title="Agentic Workflow Builder",
    description="API for creating and executing multi-step LLM workflows",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}



@app.post("/workflows", response_model=Workflow)
async def create_workflow(request: WorkflowCreate) -> Workflow:
    workflow = Workflow(
        name=request.name,
        description=request.description,
        steps=request.steps,
        webhook_url=request.webhook_url,
    )
    workflows[workflow.id] = workflow
    return workflow


@app.get("/workflows", response_model=list[Workflow])
async def list_workflows() -> list[Workflow]:
    return list(workflows.values())


@app.get("/workflows/{workflow_id}", response_model=Workflow)
async def get_workflow(workflow_id: UUID) -> Workflow:
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflows[workflow_id]


@app.put("/workflows/{workflow_id}", response_model=Workflow)
async def update_workflow(workflow_id: UUID, request: WorkflowUpdate) -> Workflow:
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    workflow = workflows[workflow_id]
    update_data = request.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()
    
    updated_workflow = workflow.model_copy(update=update_data)
    workflows[workflow_id] = updated_workflow
    
    return updated_workflow


@app.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: UUID):
    """Delete a workflow."""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    del workflows[workflow_id]
    return {"status": "deleted"}


# WORKFLOW EXECUTION

@app.post("/workflows/{workflow_id}/run", response_model=RunWorkflowResponse)
async def run_workflow(workflow_id: UUID, request: RunWorkflowRequest) -> RunWorkflowResponse:
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    workflow = workflows[workflow_id]
    run = WorkflowRun(
        workflow_id=workflow_id,
        status=RunStatus.PENDING,
        context=request.initial_context,
    )
    workflow_runs[run.id] = run
    websocket_connections[run.id] = []
    
    # Store pending events until WebSocket connects
    pending_events[run.id] = []
    
    asyncio.create_task(execute_workflow_background(workflow, run, request.initial_context))
    
    return RunWorkflowResponse(
        run_id=run.id,
        websocket_url=f"/runs/{run.id}/events",
    )


async def execute_workflow_background(
    workflow: Workflow,
    run: WorkflowRun,
    initial_context: str,
) -> None:
    
    async def broadcast_event(event: ExecutionEvent) -> None:
        connections = websocket_connections.get(run.id, [])
        
        # If no WebSocket connected yet, buffer the event
        if not connections and run.id in pending_events:
            pending_events[run.id].append(event)
            return
        
        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(event.model_dump(mode="json"))
            except Exception:
                disconnected.append(ws)
        
        for ws in disconnected:
            if ws in websocket_connections.get(run.id, []):
                websocket_connections[run.id].remove(ws)
    
    # Small delay to allow WebSocket to connect
    await asyncio.sleep(0.5)

    # Move run into RUNNING state immediately so /runs/{id} updates while executing.
    run.status = RunStatus.RUNNING
    run.started_at = datetime.utcnow()
    workflow_runs[run.id] = run
    
    try:
        llm_client = create_unbound_client()
    except ValueError as e:
        run.status = RunStatus.FAILED
        run.failure_reason = str(e)
        run.finished_at = datetime.utcnow()
        workflow_runs[run.id] = run

        # Emit an explicit failure event so clients relying on WS see it.
        await broadcast_event(
            ExecutionEvent(
                event=EventType.RUN_FAILED,
                run_id=run.id,
                payload={"reason": str(e)},
            )
        )
        return
    
    validator = ValidatorDispatcher()
    
    def on_event(event: ExecutionEvent) -> None:
        asyncio.create_task(broadcast_event(event))
    
    orchestrator = Orchestrator(
        llm_client=llm_client,
        validator=validator,
        on_event=on_event,
    )
    
    try:
        completed_run = await orchestrator.run(workflow, initial_context, run_id=run.id)
        
        # Update stored run with results
        workflow_runs[run.id] = completed_run
        
    except Exception as e:
        # Unexpected error — mark as failed
        run.status = RunStatus.FAILED
        run.failure_reason = f"Unexpected error: {str(e)}"
        run.finished_at = datetime.utcnow()
        workflow_runs[run.id] = run


# =============================================================================
# RUN STATUS
# =============================================================================

@app.get("/runs/{run_id}", response_model=WorkflowRun)
async def get_run(run_id: UUID) -> WorkflowRun:
    """Get the current status of a workflow run."""
    if run_id not in workflow_runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return workflow_runs[run_id]


@app.get("/runs", response_model=list[WorkflowRun])
async def list_runs() -> list[WorkflowRun]:
    """List all workflow runs."""
    return list(workflow_runs.values())


# =============================================================================
# WEBSOCKET FOR LIVE EVENTS
# =============================================================================

@app.websocket("/runs/{run_id}/events")
async def websocket_events(websocket: WebSocket, run_id: UUID):
    await websocket.accept()
    if run_id not in workflow_runs:
        await websocket.send_json({"error": "Run not found"})
        await websocket.close()
        return
    
    if run_id not in websocket_connections:
        websocket_connections[run_id] = []
    websocket_connections[run_id].append(websocket)
    
    # Send any pending/buffered events
    if run_id in pending_events:
        for event in pending_events[run_id]:
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception:
                pass
        pending_events[run_id] = []  # Clear after sending
    
    run = workflow_runs[run_id]
    await websocket.send_json({
        "event_type": "connected",
        "run_id": str(run_id),
        "status": run.status.value,
        "payload": {},
    })
    
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,  
                )
                if message == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                run = workflow_runs.get(run_id)
                if run and run.status in [RunStatus.COMPLETED, RunStatus.FAILED]:
                    # Send final status and close
                    await websocket.send_json({
                        "type": "run_ended",
                        "status": run.status.value,
                        "final_output": run.final_output,
                        "failure_reason": run.failure_reason,
                    })
                    break
                    
    except WebSocketDisconnect:
        pass
    finally:
        # Unregister connection
        if run_id in websocket_connections:
            if websocket in websocket_connections[run_id]:
                websocket_connections[run_id].remove(websocket)



@app.get("/workflows/{workflow_id}/export")
async def export_workflow(workflow_id: UUID):
    """Export a workflow as JSON for sharing/backup."""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    workflow = workflows[workflow_id]
    return workflow.model_dump(mode="json")


@app.post("/workflows/import", response_model=Workflow)
async def import_workflow(workflow_data: dict):
    try:
        # Create new workflow from data (generates new ID)
        workflow = Workflow(
            name=workflow_data.get("name", "Imported Workflow"),
            description=workflow_data.get("description"),
            steps=workflow_data.get("steps", []),
            webhook_url=workflow_data.get("webhook_url"),
        )
        workflows[workflow.id] = workflow
        return workflow
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid workflow data: {e}")
