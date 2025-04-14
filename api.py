# api.py
import asyncio
import yaml
import os
import uuid # For generating unique trace IDs per request
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel # For request/response models

# --- Local Imports ---
# Assuming these files are in the same directory or accessible via Python path
from mcp_server_manager import MCPServerManager
from tool_agents.orchestrator_agent import create_orchestrator_agent

# --- Agent Framework Imports ---
# Base classes needed for generic creation and running
from agents import Agent, ModelSettings, Runner, trace, ItemHelpers, MessageOutputItem

# --- Configuration ---
# Load configuration path from environment or use default
APP_CONFIG_PATH = os.getenv("APP_CONFIG_PATH", "agents_config.yaml")

# --- Pydantic Models for API ---
class TaskRequest(BaseModel):
    task: str # The user's instruction for the orchestrator

class TaskResponse(BaseModel):
    result: str # The final output from the orchestration
    trace_id: str # The unique trace ID for this request

class HealthStatus(BaseModel):
    status: str
    details: Dict[str, Any]

# --- Generic Agent Creation Function (Moved from previous main.py) ---

def create_generic_agent(
    agent_config: Dict[str, Any], # Config for one agent from YAML
    mcp_manager: Optional[MCPServerManager] # Pass the manager to get servers
    ) -> Optional[Agent]:
    """
    Creates an Agent instance directly from configuration dictionary.
    """
    agent_name = agent_config.get('name', 'UnnamedAgent')
    params = agent_config.get('parameters', {})
    mcp_key = agent_config.get('mcp_server_key') # Optional
    final_agent_name = params.get('name', agent_name)

    print(f"INFO: Attempting to create generic agent: {final_agent_name} (Config Name: {agent_name}, MCP Key: {mcp_key or 'None'})")
    try:
        agent_args: Dict[str, Any] = {}
        agent_args['name'] = final_agent_name
        agent_args['instructions'] = params.get('instructions', 'No instructions provided.')
        agent_args['handoff_description'] = params.get('handoff_description')

        model_config_dict = params.get('model_settings')
        if isinstance(model_config_dict, dict):
            if mcp_key and 'tool_choice' not in model_config_dict:
                model_config_dict['tool_choice'] = 'required'
            agent_args['model_settings'] = ModelSettings(**model_config_dict)
        elif mcp_key:
            agent_args['model_settings'] = ModelSettings(tool_choice='required')

        if mcp_key:
            if mcp_manager is None:
                 print(f"ERROR: Agent '{final_agent_name}' requires MCP server '{mcp_key}', but MCP Manager is not available.")
                 return None
            try:
                server_instance = mcp_manager.get_server(mcp_key)
                agent_args['mcp_servers'] = [server_instance]
                print(f"DEBUG: Assigning server '{mcp_key}' ({getattr(server_instance,'name','?')}) to agent '{final_agent_name}'")
            except KeyError as e:
                print(f"ERROR: Agent '{final_agent_name}' needs MCP server '{mcp_key}', but it's not available/connected: {e}")
                return None
        # --- Instantiate ---
        agent_instance = Agent(**agent_args)
        print(f"INFO: Successfully created generic agent: {final_agent_name}")
        return agent_instance
    except TypeError as e:
        print(f"ERROR: TypeError creating agent '{final_agent_name}'. Check YAML. Error: {e}")
    except Exception as e:
        print(f"ERROR: Unexpected error creating generic agent '{final_agent_name}': {e}")
        import traceback
        traceback.print_exc()
    return None

# --- Agent Loading Function (Moved/adapted from previous main.py) ---

def load_and_create_agents_from_defs(
    agent_definitions: List[Dict[str, Any]], # Takes the list of definitions
    manager: Optional[MCPServerManager]       # Takes the MCP manager
    ) -> List[Agent]:
    """
    Uses the generic creator function to instantiate agents from a list of definitions.
    """
    active_agents: List[Agent] = []
    if not agent_definitions:
        print("WARNING: load_and_create_agents_from_defs received empty definitions list.")
        return active_agents

    print(f"INFO: Processing {len(agent_definitions)} agent definitions using generic creator...")
    for agent_def in agent_definitions:
        if not isinstance(agent_def, dict):
            print(f"WARNING: Skipping invalid agent definition (not a dictionary): {agent_def}")
            continue
        agent_instance = create_generic_agent(agent_def, manager)
        if agent_instance:
            active_agents.append(agent_instance)
    print(f"INFO: Successfully created {len(active_agents)} agents from provided definitions.")
    return active_agents

# --- Application State Storage ---
# Using a simple dictionary for state, could use a dedicated class
app_state: Dict[str, Any] = {
    "mcp_manager": None,
    "orchestrator_agent": None,
    "tool_agents": [] # Store the loaded agents maybe?
}

# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("INFO: Application startup sequence initiated...")
    global app_state # Modify global state dictionary

    # 1. Load Configuration from YAML
    print(f"INFO: Loading application configuration from {APP_CONFIG_PATH}...")
    app_config: Optional[Dict[str, Any]] = None
    try:
        with open(APP_CONFIG_PATH, 'r') as f:
            app_config = yaml.safe_load(f)
            if not isinstance(app_config, dict):
                raise ValueError("YAML root is not a dictionary.")
    except FileNotFoundError:
        print(f"FATAL: Configuration file not found: {APP_CONFIG_PATH}. Cannot start.")
        raise RuntimeError(f"Configuration file not found: {APP_CONFIG_PATH}")
    except Exception as e:
        print(f"FATAL: Error loading/parsing config {APP_CONFIG_PATH}: {e}. Cannot start.")
        raise RuntimeError(f"Failed to load configuration: {e}") from e

    mcp_server_configs = app_config.get('mcp_servers', {})
    agent_definitions = app_config.get('agents', [])
    print(f"INFO: Found {len(mcp_server_configs)} MCP server definitions and {len(agent_definitions)} agent definitions.")

    # 2. Initialize and Connect MCP Manager
    mcp_manager = MCPServerManager(mcp_server_configs)
    try:
        # Connect to all servers; __aenter__ returns the manager instance
        active_manager = await mcp_manager.__aenter__()
        app_state["mcp_manager"] = active_manager # Store the active manager
        print("INFO: MCP Manager successfully connected.")
    except Exception as e:
        print(f"FATAL: MCP Server connection failed during startup: {e}")
        # If MCP is critical, prevent startup
        raise RuntimeError(f"MCP Connection failed: {e}") from e

    # 3. Load Tool Agents
    print("INFO: Loading and creating tool agents...")
    try:
        # Pass the active manager instance (returned by __aenter__)
        tool_agents = load_and_create_agents_from_defs(agent_definitions=agent_definitions, manager=app_state["mcp_manager"])
        app_state["tool_agents"] = tool_agents
    except Exception as e:
        print(f"ERROR: Failed to load/create agents during startup: {e}")
        # Decide if startup should fail or continue without agents
        app_state["tool_agents"] = []
        # Optionally raise error if agents are critical: raise RuntimeError(...) from e

    # 4. Create Orchestrator Agent
    if app_state["tool_agents"]:
        print(f"INFO: Creating orchestrator agent with {len(app_state['tool_agents'])} tool(s).")
        try:
            orchestrator = create_orchestrator_agent(app_state["tool_agents"])
            app_state["orchestrator_agent"] = orchestrator
            print("INFO: Orchestrator agent created successfully.")
        except Exception as e:
             print(f"ERROR: Failed to create orchestrator agent during startup: {e}")
             # App might be degraded without orchestrator
             app_state["orchestrator_agent"] = None
    else:
         print("WARNING: No tool agents loaded, orchestrator agent cannot be created.")
         app_state["orchestrator_agent"] = None

    print("INFO: Application startup complete. Ready to serve requests.")
    yield # Application runs here

    # --- Shutdown ---
    print("INFO: Application shutdown sequence initiated...")
    manager_instance = app_state.get("mcp_manager")
    if manager_instance:
        try:
            print("INFO: Disconnecting MCP servers...")
            await manager_instance.__aexit__(None, None, None) # Cleanly disconnect
        except Exception as e:
            print(f"ERROR: Exception during MCP manager shutdown: {e}")
    else:
        print("INFO: No MCP manager found in state during shutdown.")
    print("INFO: Application shutdown complete.")


# --- FastAPI App Instance ---
# Pass the lifespan manager to the FastAPI app
app = FastAPI(title="Agent Orchestration Service", lifespan=lifespan)


# --- Dependency Injection Functions ---
# Provide safe access to shared state for request handlers

def get_mcp_manager() -> MCPServerManager:
    manager = app_state.get("mcp_manager")
    if manager is None:
        # This indicates a startup failure or logic error
        raise HTTPException(status_code=503, detail="MCP Server Manager not available.")
    return manager

def get_orchestrator() -> Agent:
    orchestrator = app_state.get("orchestrator_agent")
    if orchestrator is None:
        # Could be due to startup errors or no tool agents loaded
        raise HTTPException(status_code=503, detail="Orchestrator Agent not available.")
    return orchestrator


# --- API Endpoints ---

@app.post("/orchestrate", response_model=TaskResponse)
async def run_orchestration_endpoint(
    payload: TaskRequest,
    orchestrator: Agent = Depends(get_orchestrator) # Inject orchestrator
    # Can inject manager too if needed: manager: MCPServerManager = Depends(get_mcp_manager)
    ):
    """
    Receives a task and runs it through the loaded agent orchestrator.
    """
    request_trace_id = f"trace_{uuid.uuid4().hex}" # Unique trace ID per request
    print(f"INFO: Received task for trace_id {request_trace_id}: '{payload.task}'")

    # Use trace context manager from the agents library
    with trace(f"API Request - {request_trace_id}", trace_id=request_trace_id):
        try:
            # Run the orchestration using the injected agent
            result = await Runner.run(orchestrator, payload.task)

            # Extract final output (same logic as before)
            final_output = result.final_output
            if not final_output:
                 print("DEBUG: No explicit final_output from Runner, searching last message item.")
                 for item in reversed(result.new_items):
                     if isinstance(item, MessageOutputItem):
                         text = ItemHelpers.text_message_output(item)
                         if text:
                             final_output = text
                             break
                 if not final_output:
                      final_output = "Orchestration completed, but no specific output was generated."

            print(f"INFO: Task successful for trace_id {request_trace_id}.")
            # Return the successful response
            return TaskResponse(result=final_output, trace_id=request_trace_id)

        # --- Specific Error Handling ---
        # Example: Handle errors if the runner itself fails badly
        except Exception as e:
             print(f"ERROR: Unexpected error during task execution for trace_id {request_trace_id}: {e}")
             import traceback
             traceback.print_exc()
             # Return a generic server error
             raise HTTPException(
                 status_code=500,
                 detail=f"Internal server error during task execution. Trace ID: {request_trace_id}"
             )

@app.get("/health", response_model=HealthStatus)
async def health_check():
    """Basic health check endpoint."""
    manager = app_state.get("mcp_manager")
    orchestrator = app_state.get("orchestrator_agent")
    tool_agents = app_state.get("tool_agents", [])

    is_healthy = True
    details = {
         "mcp_manager_initialized": manager is not None,
         "mcp_servers_target_count": len(manager._configs) if manager else 0,
         "mcp_servers_active_count": len(manager._active_servers) if manager else 0,
         "orchestrator_loaded": orchestrator is not None,
         "tool_agents_loaded_count": len(tool_agents),
    }

    # Define health based on critical components being ready
    if not manager or not orchestrator:
         is_healthy = False
    if manager and len(manager._configs) > 0 and len(manager._active_servers) == 0:
         # If servers were configured but none connected, service might be unhealthy
         is_healthy = False
         details["error"] = "MCP Manager initialized but no servers are active."
    if not tool_agents: # Check if agents were defined but failed to load
         is_healthy = False
         details["error"] = "Tool agents were defined in config but failed to load."


    return HealthStatus(
        status="ok" if is_healthy else "error",
        details=details
    )

# --- Uvicorn Runner (for direct execution) ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000)) # Allow port configuration via env var
    host = os.getenv("HOST", "0.0.0.0")
    # Set reload=False for production or when debugging startup/shutdown issues
    # Set reload=True for automatic code reloading during development
    reload_flag = os.getenv("DEV_MODE", "false").lower() == "true"

    print(f"INFO: Starting Uvicorn server on {host}:{port} (Reload: {reload_flag})...")
    uvicorn.run("api:app", host=host, port=port, reload=reload_flag)