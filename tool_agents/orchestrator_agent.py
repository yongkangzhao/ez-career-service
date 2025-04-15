# tool_agents/orchestrator_agent.py
from agents import Agent, function_tool, Runner, ItemHelpers
from typing import List, Dict, Any, Tuple, Optional

# --- REMOVED TOOL_METADATA_OVERRIDES ---

def create_tool_agent(agent: Agent, tool_name: Optional[str] = None, tool_description: Optional[str] = None, max_turn: Optional[int] = 100) -> Agent:
    async def run_agent(query: str) -> str:
        result = await Runner.run(
            agent,
            query,
            max_turns=max_turn,
        )
        return ItemHelpers.text_message_outputs(result.new_items)
    return function_tool(run_agent,
        name_override=tool_name or agent.name,
        description_override=tool_description
    )


def create_orchestrator_agent(
    # Expect a list of tuples: (agent_instance, tool_metadata_dict)
    # The dict now contains {'description': ...}
    orchestrator_agent_config: Dict[str, Any],
    tool_agent_configs: List[Tuple[Agent, Dict[str, Any]]]
    ) -> Agent:
    """
    Factory function to create the orchestrator agent.
    Accepts a list of tuples, each containing an Agent instance
    and a dictionary with its desired tool description override ('description').
    The agent's 'name' is always used as the tool_name.
    """
    if not tool_agent_configs:
        print("WARNING: Creating OrchestratorAgent with no tool agents provided.")

    if not orchestrator_agent_config:
        print("WARNING: Creating OrchestratorAgent with no orchestrator agent config provided.")
        orchestrator_agent_config = {}

    agent_names = [getattr(agent, 'name', 'Unnamed') for agent, meta in tool_agent_configs]
    print(f"DEBUG: Creating OrchestratorAgent from agents: {agent_names}")

    tools_list: List = []
    tool_descriptions_for_instructions = []

    for agent, tool_meta in tool_agent_configs:
        # --- Tool Name: Always use the agent's actual name ---
        agent_name = getattr(agent, 'name', 'UnnamedAgent')
        tool_name_to_use = agent_name # Direct assignment

        # --- Tool Description Generation ---
        # 1. Prioritize 'description' from YAML (via tool_meta)
        tool_description_to_use = tool_meta.get('description') # Fetches value associated with 'description' key

        # 2. Fallback to agent's handoff_description if YAML description is missing
        if not tool_description_to_use:
            tool_description_to_use = getattr(agent, 'handoff_description', None)
            if tool_description_to_use:
                print(f"DEBUG: No 'description' in YAML for agent '{agent_name}'. Using fallback 'handoff_description'.")
            else:
                # 3. Generate generic default if both are missing
                tool_description_to_use = f"Activates the {agent_name} agent to perform its specialized task."
                print(f"DEBUG: No 'description' or 'handoff_description' found for agent '{agent_name}'. Using generic description.")
        # else: Description from YAML was found and assigned

        print(f"DEBUG: Converting agent '{agent_name}' to tool '{tool_name_to_use}' with description: '{tool_description_to_use}'")
        try:
            # agent_tool = agent.as_tool(
            #     tool_name=tool_name_to_use, # Use agent's actual name
            #     tool_description=tool_description_to_use, # Use determined description
            # )
            agent_tool = create_tool_agent(
                agent,
                tool_name=tool_name_to_use,
                tool_description=tool_description_to_use
            )
            tools_list.append(agent_tool)
            tool_descriptions_for_instructions.append(f"- {tool_name_to_use}: {tool_description_to_use}")
        except Exception as e:
            print(f"ERROR: Failed to convert agent '{agent_name}' to tool. Error: {e}")
            raise RuntimeError(f"Failed to convert agent '{agent_name}' to tool") from e

    if not tools_list:
         print("WARNING: Orchestrator created with no tools!")

    tool_details = "\n".join(tool_descriptions_for_instructions) if tools_list else "No tools available."

    return Agent(
        name=orchestrator_agent_config.get('name', "TaskOrchestratorAgent"),
        model=orchestrator_agent_config.get('model', "gpt-4-mini"),
        instructions = (f"""
**Your Role: Master Orchestrator & Task Manage
You are responsible for managing a team of specialized agents (tools) to accomplish complex user goals, such as automating job applications. Your primary objective is to **fully satisfy the user's request through persistent, step-by-step execution.**\n
**Available Tools:**
You have access to the following specialized agents, usable as tools:

{tool_details}

"""
        +
        orchestrator_agent_config.get('parameters').get('instructions')


    ),
        tools=tools_list,
    )