# api.py
import os

from dotenv import load_dotenv
load_dotenv()

import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from agents import Agent, ItemHelpers, MessageOutputItem, ModelSettings, Runner, trace
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from mcp_server_manager import MCPServerManager
from tool_agents.orchestrator_agent import create_orchestrator_agent

APP_CONFIG_PATH = os.getenv("APP_CONFIG_PATH", "agents_config.yaml")


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    result: str
    trace_id: str


class HealthStatus(BaseModel):
    status: str
    details: Dict[str, Any]


def create_generic_agent(
    agent_config: Dict[str, Any], mcp_manager: Optional[MCPServerManager]
) -> Optional[Agent]:
    agent_name = agent_config.get("name", "UnnamedAgent")
    params = agent_config.get("parameters", {})
    mcp_key = agent_config.get("mcp_server_key")
    final_agent_name = params.get("name", agent_name)
    print(
        f"INFO: Attempting to create generic agent: {final_agent_name} (Config Name: {agent_name}, MCP Key: {mcp_key or 'None'})"
    )
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
            try:
                server_instance = mcp_manager.get_server(mcp_key)
                agent_args["mcp_servers"] = [server_instance]
            except KeyError:
                return None
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
    agent_definitions: List[Dict[str, Any]], manager: Optional[MCPServerManager]
) -> List[Tuple[Agent, Dict[str, Any]]]:
    """
    Uses the generic creator function to instantiate agents and extracts
    the 'description' field from YAML for orchestrator tool metadata.
    """
    created_agents_with_meta: List[Tuple[Agent, Dict[str, Any]]] = []
    if not agent_definitions:
        return created_agents_with_meta

    print(
        f"INFO: Processing {len(agent_definitions)} agent definitions using generic creator..."
    )
    for agent_def in agent_definitions:
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
    "tool_agents_with_meta": [],  # Still store tuples
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
    agent_definitions = app_config.get("agents", [])
    print(
        f"INFO: Found {len(mcp_server_configs)} MCP server definitions and {len(agent_definitions)} agent definitions."
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
            agent_definitions=agent_definitions, manager=app_state["mcp_manager"]
        )
        app_state["tool_agents_with_meta"] = tool_agents_with_meta
    except Exception as e:
        print(f"ERROR: Failed to load/create agents during startup: {e}")
        app_state["tool_agents_with_meta"] = []

    if app_state["tool_agents_with_meta"]:
        tool_agent_count = len(app_state["tool_agents_with_meta"])
        print(f"INFO: Creating orchestrator agent with {tool_agent_count} tool(s).")
        try:
            orchestrator = create_orchestrator_agent(app_state["tool_agents_with_meta"])
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


@app.post("/orchestrate", response_model=TaskResponse)
async def run_orchestration_endpoint(
    payload: TaskRequest, orchestrator: Agent = Depends(get_orchestrator)
):
    request_trace_id = f"trace_{uuid.uuid4().hex}"
    print(f"INFO: Received task for trace_id {request_trace_id}: '{payload.task}'")
    print(
        f"INFO: OpenAI trace: https://platform.openai.com/traces/trace?trace_id={request_trace_id}"
    )

    with trace(f"API Request - {request_trace_id}", trace_id=request_trace_id):
        try:
            result = await Runner.run(orchestrator, payload.task, max_turns=100)
            final_output = result.final_output
            if not final_output:
                for item in reversed(result.new_items):
                    if isinstance(item, MessageOutputItem):
                        text = ItemHelpers.text_message_output(item)
                        if text:
                            final_output = text
                            break
                if not final_output:
                    final_output = "Orchestration completed, no specific output."
            print(f"INFO: Task successful for trace_id {request_trace_id}.")
            return TaskResponse(result=final_output, trace_id=request_trace_id)
        except Exception as e:
            print(
                f"ERROR: Unexpected error during task execution for trace_id {request_trace_id}: {e}"
            )
            import traceback

            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error. Trace ID: {request_trace_id}",
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    reload_flag = os.getenv("DEV_MODE", "false").lower() == "true"
    print(f"INFO: Starting Uvicorn server on {host}:{port} (Reload: {reload_flag})...")
    uvicorn.run("api:app", host=host, port=port, reload=reload_flag)
