# api.py
import os
import threading
import time
import queue
import json

from dotenv import load_dotenv
load_dotenv()

import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, Union
import traceback
from braintrust import init_logger
from braintrust.wrappers.openai import BraintrustTracingProcessor


import yaml
from agents import Agent, ItemHelpers, MessageOutputItem, ModelSettings, Runner, trace, set_trace_processors
from fastapi import Depends, FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mcp_server_manager import MCPServerManager
from tool_agents.orchestrator_agent import create_orchestrator_agent
from supabase import create_client

APP_CONFIG_PATH = os.getenv("APP_CONFIG_PATH", "agents_config.yaml")

# Add a cancellation queue that will be processed by a background thread
cancellation_queue = queue.Queue()

# Background thread for processing cancellations
def cancellation_monitor():
    """Background thread that monitors for cancellation requests"""
    print("INFO: Starting cancellation monitor thread")
    while True:
        try:
            # Check if there's a cancellation request in the queue
            try:
                trace_id = cancellation_queue.get(timeout=1.0)
                print(f"INFO: Processing cancellation for trace_id {trace_id} from queue")
                
                # Process the cancellation
                if trace_id in app_state["active_tasks"]:
                    try:
                        # Get the task
                        task = app_state["active_tasks"][trace_id]
                        print(f"DEBUG: Found task {trace_id} in cancellation monitor, cancelling...")
                        
                        # Cancel the task
                        task.cancel()
                        
                        # Remove from active tasks
                        del app_state["active_tasks"][trace_id]
                        print(f"INFO: Task {trace_id} cancelled successfully by background monitor")
                    except Exception as e:
                        print(f"ERROR: Background cancellation failed for {trace_id}: {e}")
                else:
                    print(f"DEBUG: Task {trace_id} not found in active_tasks during background cancellation")
            except queue.Empty:
                # No cancellation requests, continue
                pass
                
            # Sleep briefly to avoid CPU thrashing
            time.sleep(0.1)
        except Exception as e:
            print(f"ERROR in cancellation monitor: {e}")
            time.sleep(1)  # Sleep longer on error

# Start the background thread
cancellation_thread = threading.Thread(target=cancellation_monitor, daemon=True)
cancellation_thread.start()

class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    result: str
    trace_id: str


class CancelRequest(BaseModel):
    trace_id: str


class CancelResponse(BaseModel):
    success: bool
    message: str


class HealthStatus(BaseModel):
    status: str
    details: Dict[str, Any]


class TaskStatusResponse(BaseModel):
    active_tasks: List[str]
    count: int


class ForceKillRequest(BaseModel):
    trace_id: str
    force: bool = False


class ForceKillResponse(BaseModel):
    success: bool
    message: str


class TaskStatusRequest(BaseModel):
    trace_id: str


class TaskStatusDetailResponse(BaseModel):
    active: bool
    message: str


class OrchestrateResponse(BaseModel):
    trace_id: str
    status: str


class TaskResultResponse(BaseModel):
    trace_id: str
    status: str # e.g., "pending", "completed", "failed", "cancelled"
    result: Optional[str] = None


class ReprocessRequest(BaseModel):
    issue_id: str
    additional_info: Dict[str, Any] = {}


def create_generic_agent(
    agent_config: Dict[str, Any], mcp_manager: Optional[MCPServerManager]
) -> Optional[Agent]:
    agent_name = agent_config.get("name", "UnnamedAgent")
    params = agent_config.get("parameters", {})
    mcp_key = agent_config.get("mcp_server_key")
    print(f"INFO: Creating generic agent: {agent_name} (MCP Key: {mcp_key or 'None'})")
    final_agent_name = params.get("name", agent_name)
    
    try:
        agent_args: Dict[str, Any] = {}
        agent_args["name"] = final_agent_name
        agent_args["instructions"] = params.get(
            "instructions", "No instructions provided."
        )
        agent_args["handoff_description"] = params.get("handoff_description")
        agent_args["model"] = params.get("model", None)

        model_config_dict = params.get("model_settings")
        if isinstance(model_config_dict, dict):
            if mcp_key and "tool_choice" not in model_config_dict:
                model_config_dict["tool_choice"] = "required"
            agent_args["model_settings"] = ModelSettings(**model_config_dict)
        elif mcp_key:
            agent_args["model_settings"] = ModelSettings(tool_choice="required")

        if mcp_key:
            if mcp_manager is None:
                return None
            
            # Parse mcp_key as potentially space-separated values
            mcp_keys = mcp_key.split() if isinstance(mcp_key, str) else [mcp_key]
            mcp_servers = []
            
            for key in mcp_keys:
                try:
                    server_instance = mcp_manager.get_server(key)
                    mcp_servers.append(server_instance)
                except KeyError:
                    print(f"WARNING: MCP server with key '{key}' not found")
            
            if not mcp_servers:
                print(f"ERROR: None of the specified MCP servers were found: {mcp_key}")
                return None
                
            agent_args["mcp_servers"] = mcp_servers
            
        agent_instance = Agent(**agent_args)
        print(f"INFO: Successfully created generic agent: {final_agent_name}")
        return agent_instance
    except Exception as e:
        print(
            f"ERROR: Unexpected error creating generic agent '{final_agent_name}': {e}"
        )
        import traceback

        traceback.print_exc()
    return None


def load_and_create_agents_from_defs(
    tool_: List[Dict[str, Any]], manager: Optional[MCPServerManager]
) -> List[Tuple[Agent, Dict[str, Any]]]:
    """
    Uses the generic creator function to instantiate agents and extracts
    the 'description' field from YAML for orchestrator tool metadata.
    """
    created_agents_with_meta: List[Tuple[Agent, Dict[str, Any]]] = []
    if not tool_:
        return created_agents_with_meta

    print(
        f"INFO: Processing {len(tool_)} agent definitions using generic creator..."
    )
    for agent_def in tool_:
        if not isinstance(agent_def, dict):
            continue  # Skip invalid

        agent_instance = create_generic_agent(agent_def, manager)
        if agent_instance:
            tool_meta = {"description": agent_def.get("description")}
            # Append the tuple (agent, metadata_dict)
            created_agents_with_meta.append((agent_instance, tool_meta))

    print(
        f"INFO: Successfully processed definitions, created {len(created_agents_with_meta)} agents."
    )
    return created_agents_with_meta


app_state: Dict[str, Any] = {
    "mcp_manager": None,
    "orchestrator_agent": None,
    "tool_agents_with_meta": [],
    "active_tasks": {},  # Stores the asyncio.Task objects
    "task_results": {}, # Stores results/errors keyed by trace_id
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO: Application startup sequence initiated...")
    global app_state
    print(f"INFO: Loading application configuration from {APP_CONFIG_PATH}...")
    app_config: Optional[Dict[str, Any]] = None
    try:
        with open(APP_CONFIG_PATH, "r") as f:
            app_config = yaml.safe_load(f)
        if not isinstance(app_config, dict):
            raise ValueError("YAML root is not a dictionary.")
    except FileNotFoundError:
        raise RuntimeError(f"Configuration file not found: {APP_CONFIG_PATH}")
    except Exception as e:
        raise RuntimeError(f"Failed to load configuration: {e}") from e

    mcp_server_configs = app_config.get("mcp_servers", {})
    tool_agent_definitions = app_config.get("tool_agents", [])
    print(
        f"INFO: Found {len(mcp_server_configs)} MCP server definitions and {len(tool_agent_definitions)} agent definitions."
    )

    mcp_manager = MCPServerManager(mcp_server_configs)
    try:
        active_manager = await mcp_manager.__aenter__()
        app_state["mcp_manager"] = active_manager
        print("INFO: MCP Manager successfully connected.")
    except Exception as e:
        raise RuntimeError(f"MCP Connection failed: {e}") from e

    print("INFO: Loading and creating tool agents...")    
    try:
        tool_agents_with_meta = load_and_create_agents_from_defs(
            tool_=tool_agent_definitions, manager=app_state["mcp_manager"]
        )
        app_state["tool_agents_with_meta"] = tool_agents_with_meta
    except Exception as e:
        print(f"ERROR: Failed to load/create agents during startup: {e}")
        app_state["tool_agents_with_meta"] = []

    if app_state["tool_agents_with_meta"]:
        tool_agent_count = len(app_state["tool_agents_with_meta"])
        print(f"INFO: Creating orchestrator agent with {tool_agent_count} tool(s).")
        orchestrator_agent_config = app_config.get("orchestrator_agent", [])
        if orchestrator_agent_config:
            print(
                f"INFO: Found orchestrator agent config."
            )
        else:
            print(
                f"WARNING: No orchestrator agent config found. Using default."
            )
        try:
            orchestrator = create_orchestrator_agent(orchestrator_agent_config, app_state["tool_agents_with_meta"])
            app_state["orchestrator_agent"] = orchestrator
            print("INFO: Orchestrator agent created successfully.")
        except Exception as e:
            print(f"ERROR: Failed to create orchestrator agent during startup: {e}")
            app_state["orchestrator_agent"] = None
    else:
        print("WARNING: No tool agents loaded, orchestrator agent cannot be created.")
        app_state["orchestrator_agent"] = None

    print("INFO: Application startup complete. Ready to serve requests.")
    yield

    print("INFO: Application shutdown sequence initiated...")
    manager_instance = app_state.get("mcp_manager")
    if manager_instance:
        try:
            await manager_instance.__aexit__(None, None, None)
        except Exception as e:
            print(f"ERROR: Exception during MCP manager shutdown: {e}")
    print("INFO: Application shutdown complete.")


app = FastAPI(title="EZ-Career Backend Service", lifespan=lifespan)

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_mcp_manager() -> MCPServerManager:
    manager = app_state.get("mcp_manager")
    if manager is None:
        raise HTTPException(status_code=503, detail="MCP Server Manager not available.")
    return manager


def get_orchestrator() -> Agent:
    orchestrator = app_state.get("orchestrator_agent")
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator Agent not available.")
    return orchestrator


async def run_agent_task_background(
    orchestrator: Agent, 
    task_str: str, 
    trace_id: str # Already passed in, perfect!
):
    """Runs the agent task and stores the result or error, with tracing."""
    # The trace block wraps the core logic including error handling for that logic
    set_trace_processors([BraintrustTracingProcessor(init_logger("openai-agent"))])
    with trace(f"Agent Execution - {trace_id}", trace_id=trace_id):
        print(f"BACKGROUND: Starting task {trace_id} inside trace block")
        try:
            # --- Core Agent Logic ---
            result = await Runner.run(orchestrator, task_str, max_turns=100)

            final_output = result.final_output
            # Find output if not directly available (same logic as before)
            if not final_output:
                for item in reversed(result.new_items):
                    if isinstance(item, MessageOutputItem): # Use your actual class
                        text = ItemHelpers.text_message_output(item) # Use your actual helper
                        if text:
                            final_output = text
                            break
                if not final_output:
                    final_output = "Orchestration completed, no specific output."
            
            # Store successful result
            app_state["task_results"][trace_id] = {"status": "completed", "result": final_output}
            print(f"BACKGROUND: Task {trace_id} completed successfully.")
            # --- End Core Agent Logic ---

        except asyncio.CancelledError:
            # Handle cancellation specifically (occurs if task.cancel() is called)
            app_state["task_results"][trace_id] = {"status": "cancelled", "result": "Task was cancelled"}
            print(f"BACKGROUND: Task {trace_id} was cancelled.")
            # Optionally re-raise if the trace context manager needs to know about cancellation
            # raise 

        except Exception as e:
            # Handle other exceptions during agent execution
            print(f"BACKGROUND ERROR: Task {trace_id} failed: {e}")
            traceback.print_exc() # Log the full traceback
            app_state["task_results"][trace_id] = {"status": "failed", "result": f"Internal server error: {str(e)}"}
            # The exception will be caught by the trace context manager's try...except if it's configured to do so
            # No need to re-raise here unless needed for outer layers not shown

        finally:
            # This finally block ensures cleanup happens regardless of success, failure, or cancellation.
            # It runs *after* the main try/except blocks within the 'with trace' block complete.
            if trace_id in app_state["active_tasks"]:
                try:
                    del app_state["active_tasks"][trace_id]
                    print(f"BACKGROUND: Removed task {trace_id} from active_tasks.")
                except KeyError:
                    # This might happen in race conditions if cancellation occurs right near completion
                    print(f"BACKGROUND WARNING: Task {trace_id} already removed from active_tasks during final cleanup.")
            else:
                 print(f"BACKGROUND WARNING: Task {trace_id} not found in active_tasks for final cleanup.")
            
            print(f"BACKGROUND: Final cleanup for task {trace_id} finished.")
            # The 'with trace(...)' block finishes after this 'finally' block completes.



@app.post("/orchestrate", response_model=OrchestrateResponse, status_code=202)
async def run_orchestration_endpoint(
    payload: TaskRequest, 
    background_tasks: BackgroundTasks, 
    orchestrator: Agent = Depends(get_orchestrator)
):
    request_trace_id = f"trace_{uuid.uuid4().hex}"
    print(f"INFO: Received task for trace_id {request_trace_id}: '{payload.task}'")
    print(
        f"INFO: OpenAI trace: https://platform.openai.com/traces/trace?trace_id={request_trace_id}"
    )

    # Create the agent task
    agent_task = asyncio.create_task(
        run_agent_task_background(orchestrator, payload.task, request_trace_id)
    )
    
    # Store the task object itself for cancellation
    app_state["active_tasks"][request_trace_id] = agent_task
    print(f"DEBUG: Registered task with trace_id {request_trace_id}")

    # Add a background task to await the agent_task's completion 
    # (This is slightly redundant with the finally block in run_agent_task_background, 
    # but provides an extra layer of cleanup assurance)
    # background_tasks.add_task(agent_task) # Simplified: agent_task itself handles cleanup
    
    # Return immediately with 202 Accepted
    return OrchestrateResponse(trace_id=request_trace_id, status="accepted")


@app.post("/cancel", response_model=CancelResponse)
async def cancel_orchestration_endpoint(payload: CancelRequest):
    """
    Cancel a running orchestration task.
    This now uses a background thread to ensure cancellation works even if the main thread is busy.
    """
    try:
        trace_id = payload.trace_id
        print(f"INFO: Received cancellation request for trace_id {trace_id}")
        print(f"DEBUG: Request payload: {payload}")
        
        # Log active tasks before cancellation
        active_tasks = list(app_state["active_tasks"].keys())
        print(f"DEBUG: Active tasks before cancellation: {active_tasks}")
        
        # Check if the task exists
        if trace_id not in app_state["active_tasks"]:
            print(f"DEBUG: Task {trace_id} not found in active_tasks")
            return CancelResponse(
                success=False, 
                message=f"No active task found with trace_id: {trace_id}"
            )
        
        # Add to cancellation queue for background processing
        # This ensures the cancellation happens even if the main thread is busy
        print(f"DEBUG: Adding cancellation request for {trace_id} to queue")
        cancellation_queue.put(trace_id)
        
        # The actual cancellation will be processed by the background thread
        return CancelResponse(
            success=True,
            message=f"Cancellation request for {trace_id} has been queued"
        )
    except Exception as e:
        print(f"ERROR: Unexpected error in cancel_orchestration_endpoint: {e}")
        import traceback
        traceback.print_exc()
        return CancelResponse(
            success=False,
            message=f"Server error during cancellation: {str(e)}"
        )


@app.get("/health", response_model=HealthStatus)
async def health_check():
    manager = app_state.get("mcp_manager")
    orchestrator = app_state.get("orchestrator_agent")
    tool_agents_with_meta = app_state.get("tool_agents_with_meta", [])
    is_healthy = True
    details = {
        "mcp_manager_initialized": manager is not None,
        "mcp_servers_target_count": len(manager._configs) if manager else 0,
        "mcp_servers_active_count": len(manager._active_servers) if manager else 0,
        "orchestrator_loaded": orchestrator is not None,
        "tool_agents_loaded_count": len(tool_agents_with_meta),
    }
    if not manager or not orchestrator:
        is_healthy = False
    if manager and len(manager._configs) > 0 and len(manager._active_servers) == 0:
        is_healthy = False
        details["error"] = "MCP Manager active but no servers connected."
    agent_defs_count = 0
    try:
        with open(APP_CONFIG_PATH, "r") as f:
            agent_defs_count = len(yaml.safe_load(f).get("agents", []))
    except:
        pass  # Ignore errors here, focus on loaded state
    if (
        orchestrator is None
        and agent_defs_count > 0
        and len(tool_agents_with_meta) == 0
    ):
        details["error"] = "Tool agents defined in config but failed to load/create."
        is_healthy = False
    elif orchestrator is None and len(tool_agents_with_meta) > 0:
        details["error"] = "Orchestrator failed to load despite tools loading."
        is_healthy = False

    return HealthStatus(status="ok" if is_healthy else "error", details=details)


@app.get("/tasks/status", response_model=TaskStatusResponse)
async def get_task_status():
    """Returns the list of currently active tasks."""
    active_tasks = list(app_state["active_tasks"].keys())
    return TaskStatusResponse(
        active_tasks=active_tasks,
        count=len(active_tasks)
    )


@app.post("/kill", response_model=ForceKillResponse)
async def force_kill_endpoint(payload: ForceKillRequest):
    """
    Forcefully kill a task without waiting for it to respond to cancellation.
    This is a more aggressive version of the cancel endpoint.
    """
    trace_id = payload.trace_id
    print(f"INFO: Received FORCE KILL request for trace_id {trace_id}")
    
    if trace_id not in app_state["active_tasks"]:
        active_tasks = list(app_state["active_tasks"].keys())
        print(f"DEBUG: Active tasks: {active_tasks}")
        print(f"DEBUG: Could not find task with trace_id: {trace_id}")
        return ForceKillResponse(
            success=False,
            message=f"No active task found with trace_id: {trace_id}"
        )
    
    try:
        # Mark this as a high-priority cancellation
        print(f"DEBUG: Adding force kill request for {trace_id} to queue")
        cancellation_queue.put(trace_id)
        
        # Also try to force remove immediately in case queue is backed up
        try:
            if trace_id in app_state["active_tasks"]:
                del app_state["active_tasks"][trace_id]
                print(f"INFO: Task {trace_id} forcefully removed directly from active tasks")
        except Exception as direct_removal_error:
            print(f"ERROR: Direct task removal failed: {direct_removal_error}")
            # Continue anyway, the queue will handle it
        
        return ForceKillResponse(
            success=True, 
            message=f"Task {trace_id} has been queued for immediate termination"
        )
    except Exception as e:
        print(f"ERROR: Failed to kill task {trace_id}: {e}")
        import traceback
        traceback.print_exc()
        return ForceKillResponse(
            success=False,
            message=f"Failed to kill task: {str(e)}"
        )


@app.post("/tasks/check", response_model=TaskStatusDetailResponse)
async def check_specific_task(payload: TaskStatusRequest):
    """
    Check if a specific task is active.
    """
    trace_id = payload.trace_id
    active_tasks = list(app_state["active_tasks"].keys())
    
    if trace_id in active_tasks:
        return TaskStatusDetailResponse(
            active=True,
            message=f"Task {trace_id} is active"
        )
    else:
        return TaskStatusDetailResponse(
            active=False,
            message=f"Task {trace_id} is not active"
        )


@app.get("/tasks/result/{trace_id}", response_model=TaskResultResponse)
async def get_task_result(trace_id: str):
    """Poll for the result of a background task."""
    if trace_id in app_state["task_results"]:
        # Result is ready (completed, failed, or cancelled)
        result_data = app_state["task_results"][trace_id]
        print(f"DEBUG: Found result for {trace_id}: {result_data['status']}")
        # Remove result after fetching once to prevent memory leak?
        # Consider a TTL or cleanup strategy if results are large/numerous
        # del app_state["task_results"][trace_id]
        return TaskResultResponse(trace_id=trace_id, **result_data)
        
    elif trace_id in app_state["active_tasks"]:
        # Task is still running
        print(f"DEBUG: Task {trace_id} is still pending.")
        return TaskResultResponse(trace_id=trace_id, status="pending", result=None)
        
    else:
        # Task not found (either never existed or already cleaned up)
        print(f"DEBUG: Task {trace_id} not found.")
        raise HTTPException(status_code=404, detail=f"Task {trace_id} not found")


@app.post("/reprocess_application", response_model=OrchestrateResponse)
async def reprocess_application(
    payload: ReprocessRequest,
    background_tasks: BackgroundTasks,
    orchestrator: Agent = Depends(get_orchestrator)
):
    """
    Reprocess an application that previously had issues
    """
    try:
        # Get the issue details from Supabase
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(supabase_url, supabase_key)
        
        response = supabase_client.table("application_issues").select("*").eq("id", payload.issue_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Issue not found")
            
        issue = response.data[0]
        
        # Create a new trace ID
        request_trace_id = f"trace_{uuid.uuid4().hex}"
        
        # Create a specific task for this reprocessing
        task = (
            f"Reprocess application for {issue['position']} at {issue['company']}. "
            f"Previous issue was: {issue['issue_type']}: {issue['issue_details']}. "
            f"Additional information has been provided: {json.dumps(payload.additional_info)}. "
            f"Focus specifically on completing this application with the new information."
        )
        
        # Update the issue as resolved
        supabase_client.table("application_issues").update({
            "status": "resolved",
            "resolved_at": supabase_client.table("application_issues").sql("now()"),
            "resolution_note": f"Reprocessing initiated with additional information: {json.dumps(payload.additional_info)}"
        }).eq("id", payload.issue_id).execute()
        
        # Create a new task for the agent
        agent_task = asyncio.create_task(
            run_agent_task_background(orchestrator, task, request_trace_id)
        )
        
        # Register the task
        app_state["active_tasks"][request_trace_id] = agent_task
        
        print(f"INFO: Reprocessing application for issue {payload.issue_id} with trace_id {request_trace_id}")
        
        return OrchestrateResponse(trace_id=request_trace_id, status="accepted")
        
    except Exception as e:
        print(f"ERROR: Failed to reprocess application: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error reprocessing application: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    reload_flag = os.getenv("DEV_MODE", "false").lower() == "true"
    print(f"INFO: Starting Uvicorn server on {host}:{port} (Reload: {reload_flag})...")
    uvicorn.run("api:app", host=host, port=port, reload=reload_flag)
