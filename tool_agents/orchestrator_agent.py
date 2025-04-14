# agents/orchestrator_agent.py
# (Code from the previous step, no changes needed for this refactor)
from agents import Agent
from typing import List, Optional # Ensure List/Optional type hints are imported

# Optional: Define preferred tool names/descriptions for specific agent names
# This allows overriding the auto-generated ones if desired.
TOOL_METADATA_OVERRIDES = {
    "BrowserToolAgent": {
        "tool_name": "browser_control", # Shorter, more user-friendly tool name
        "tool_description": "Use this tool to control a web browser: navigate, screenshot, click, input text etc."
    },
    "PlanningAgent": {
         "tool_name": "task_planner",
         "tool_description": "Use this tool to break down a complex goal into smaller steps."
    }
    # Add overrides for other specific agent names here if needed
}

def create_orchestrator_agent(tool_agents: List[Agent]) -> Agent:
    """
    Factory function to create the orchestrator agent.
    Accepts a list of Agent objects that will be converted internally into tools.
    """
    if not tool_agents:
        print("WARNING: Creating OrchestratorAgent with no tool agents provided.")

    print(f"DEBUG: Creating OrchestratorAgent from agents: {[a.name for a in tool_agents]}")

    tools_list: List = []
    tool_descriptions_for_instructions = []

    for agent in tool_agents:
        # Ensure agent has a name attribute
        agent_name = getattr(agent, 'name', 'UnnamedAgent')

        # --- Tool Metadata Generation ---
        override = TOOL_METADATA_OVERRIDES.get(agent_name)
        if override:
            tool_name = override.get('tool_name', f"{agent_name}_as_tool") # Use override or default format
            tool_description = override.get('tool_description', f"Activate the {agent_name} agent.")
            print(f"DEBUG: Using override metadata for agent '{agent_name}'.")
        else:
            # Default generation if no override
            tool_name = f"{agent_name}_as_tool" # Default tool name format
            # Prefer the agent's handoff_description if available and non-empty.
            tool_description = getattr(agent, 'handoff_description', None)
            if not tool_description: # Checks for None or empty string
                tool_description = f"Activates the {agent_name} agent to perform its specialized task."
                print(f"DEBUG: No handoff_description or override for agent '{agent_name}'. Using generic description.")
            # else: No need for else, description is already set
            #     print(f"DEBUG: Using handoff_description for agent '{agent_name}'.")


        print(f"DEBUG: Converting agent '{agent_name}' to tool '{tool_name}' with description: '{tool_description}'")
        # Convert the agent to an AgentTool instance here
        try:
            # Ensure parameters passed to as_tool are correct
            agent_tool = agent.as_tool(
                tool_name=tool_name,
                tool_description=tool_description,
            )
            tools_list.append(agent_tool)
            # Use the final tool name and description for the orchestrator's instructions
            tool_descriptions_for_instructions.append(f"- {tool_name}: {tool_description}")
        except Exception as e:
            print(f"ERROR: Failed to convert agent '{agent_name}' to tool. Error: {e}")
            # Depending on desired robustness, either skip or raise
            # continue # Option: Skip this agent if conversion fails
            raise RuntimeError(f"Failed to convert agent '{agent_name}' to tool") from e


    if not tools_list:
         print("WARNING: Orchestrator created with no tools!")

    # Dynamically build instructions based on the created tools
    tool_details = "\n".join(tool_descriptions_for_instructions) if tools_list else "No tools available."

    # Return the configured orchestrator agent
    return Agent(
        name="TaskOrchestratorAgent", # Can make this name configurable too if needed
        instructions=(
            "You are a master orchestrator. Your goal is to accomplish the user's overall task "
            "by deciding which specialized tool agent to activate and when. You have the following tools available:\n"
            f"{tool_details}\n\n"
            "Analyze the user's request and the current situation. Select the single best tool "
            "to make progress towards the goal. Explain your choice briefly. "
            "Execute the chosen tool. Report the final outcome clearly after the tool execution is complete."
        ),
        tools=tools_list, # Pass the list of created AgentTool objects
        # Orchestrator decides, so usually no tool_choice='required' unless it ONLY delegates
    )