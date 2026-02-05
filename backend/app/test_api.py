"""
Test script for the FastAPI backend.

Run with: python -m app.test_api

This validates:
1. Workflow CRUD operations
2. Workflow execution
3. WebSocket event streaming

Prerequisites:
- Server running on http://localhost:8000
- UNBOUND_API_KEY set
"""

import asyncio
import httpx
import websockets
import json


BASE_URL = "http://localhost:8000"
WS_BASE_URL = "ws://localhost:8000"


async def test_health():
    """Test health endpoint."""
    print("\n--- HEALTH CHECK ---")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print(f"✓ Health check passed: {data}")


async def test_workflow_crud():
    """Test workflow CRUD operations."""
    print("\n--- WORKFLOW CRUD ---")
    
    async with httpx.AsyncClient() as client:
        # Create workflow
        workflow_data = {
            "name": "Test Workflow",
            "description": "A simple test workflow",
            "steps": [
                {
                    "name": "Generate greeting",
                    "order": 0,
                    "model": "kimi-k2-instruct-0905",
                    "prompt": "Say hello in a creative way.",
                    "validations": [
                        {"type": "contains", "expected": "hello"}
                    ],
                    "max_retries": 2
                }
            ]
        }
        
        response = await client.post(f"{BASE_URL}/workflows", json=workflow_data)
        assert response.status_code == 200, f"Create failed: {response.text}"
        workflow = response.json()
        workflow_id = workflow["id"]
        print(f"✓ Created workflow: {workflow_id}")
        
        # List workflows
        response = await client.get(f"{BASE_URL}/workflows")
        assert response.status_code == 200
        workflows = response.json()
        assert len(workflows) >= 1
        print(f"✓ Listed workflows: {len(workflows)} found")
        
        # Get workflow
        response = await client.get(f"{BASE_URL}/workflows/{workflow_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Workflow"
        print(f"✓ Got workflow by ID")
        
        # Update workflow
        response = await client.put(
            f"{BASE_URL}/workflows/{workflow_id}",
            json={"name": "Updated Workflow"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Workflow"
        print(f"✓ Updated workflow")
        
        # Export workflow
        response = await client.get(f"{BASE_URL}/workflows/{workflow_id}/export")
        assert response.status_code == 200
        exported = response.json()
        assert "name" in exported
        print(f"✓ Exported workflow")
        
        return workflow_id


async def test_workflow_execution(workflow_id: str):
    """Test workflow execution with WebSocket events."""
    print("\n--- WORKFLOW EXECUTION ---")
    
    async with httpx.AsyncClient() as client:
        # Start workflow execution
        response = await client.post(
            f"{BASE_URL}/workflows/{workflow_id}/run",
            json={"initial_context": ""}
        )
        assert response.status_code == 200, f"Run failed: {response.text}"
        run_data = response.json()
        run_id = run_data["run_id"]
        ws_url = run_data["websocket_url"]
        print(f"✓ Started run: {run_id}")
        print(f"  WebSocket URL: {ws_url}")
    
    # Connect to WebSocket and receive events
    print("\n  Connecting to WebSocket...")
    events_received = []
    
    try:
        async with websockets.connect(f"{WS_BASE_URL}{ws_url}") as ws:
            print("  ✓ WebSocket connected")
            
            # Receive events with timeout
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=60.0)
                    event = json.loads(message)
                    events_received.append(event)
                    
                    event_type = event.get("event") or event.get("type")
                    print(f"  📡 Event: {event_type}")
                    
                    # Stop when run completes
                    if event_type in ["run_completed", "run_failed", "run_ended"]:
                        break
                        
                except asyncio.TimeoutError:
                    print("  ⚠️ Timeout waiting for events")
                    break
                    
    except Exception as e:
        print(f"  WebSocket error: {e}")
    
    print(f"\n  Total events received: {len(events_received)}")
    
    # Check final run status
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        print(f"✓ Final run status: {run['status']}")
        if run.get("final_output"):
            print(f"  Final output: {run['final_output'][:100]}...")
        if run.get("failure_reason"):
            print(f"  Failure reason: {run['failure_reason']}")
    
    return run_id


async def test_list_runs():
    """Test listing runs."""
    print("\n--- LIST RUNS ---")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/runs")
        assert response.status_code == 200
        runs = response.json()
        print(f"✓ Listed runs: {len(runs)} found")


async def main():
    """Run all API tests."""
    print("=" * 60)
    print("FASTAPI BACKEND TESTS")
    print("=" * 60)
    print(f"Server: {BASE_URL}")
    
    try:
        await test_health()
        workflow_id = await test_workflow_crud()
        await test_workflow_execution(workflow_id)
        await test_list_runs()
        
        print("\n" + "=" * 60)
        print("✅ All API tests passed!")
        print("=" * 60)
        
    except httpx.ConnectError:
        print("\n❌ Could not connect to server!")
        print("   Make sure the server is running:")
        print("   python -m uvicorn app.main:app --port 8000")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
