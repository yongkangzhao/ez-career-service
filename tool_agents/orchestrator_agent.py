# tool_agents/orchestrator_agent.py
from agents import Agent
from typing import List, Dict, Any, Tuple, Optional

# --- REMOVED TOOL_METADATA_OVERRIDES ---

def create_orchestrator_agent(
    # Expect a list of tuples: (agent_instance, tool_metadata_dict)
    # The dict now contains {'description': ...}
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
            agent_tool = agent.as_tool(
                tool_name=tool_name_to_use, # Use agent's actual name
                tool_description=tool_description_to_use, # Use determined description
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
        name="TaskOrchestratorAgent",
        instructions = (f"""
        **Your Role: Master Orchestrator & Task Manage
        You are responsible for managing a team of specialized agents (tools) to accomplish complex user goals, such as automating job applications. Your primary objective is to **fully satisfy the user's request through persistent, step-by-step execution.**\n
        **Available Tools:**
        You have access to the following specialized agents, usable as tools:

        "{tool_details}"
        
        **Your Workflow & Responsibilities:**
        1.  **Deconstruct the Request:** Carefully analyze the user's request. Identify the ultimate goal and break it down into a logical sequence of sub-tasks or steps. **Do not assume the task can be done in one step.** For complex tasks like job applications, anticipate multiple stages (e.g., search, filter, analyze details, interact with forms).
        2.  **Strategic Tool Selection:** For *each* step in your plan, select the *single most appropriate tool* from the available list. Use the tool descriptions provided above to make an informed decision. Choose the tool best suited for the specific sub-task at hand.
        3.  **Formulate Precise Tool Instructions:** This is critical. When you decide to use a tool, you must provide it with **clear, specific, detailed, and unambiguous instructions.**
            * Include ALL necessary information the tool needs, based on the current step, user request, and information gathered from previous steps.
            * If invoking `BrowserToolAgent`, specify exact URLs, precise actions (click selector, input text into selector), and the text to input.
            * If invoking `PlanningAgent`, clearly state the goal that needs planning.
            * **Avoid vague commands.** Think like you are writing a command for a script; precision is key.
        4.  **Execute and Monitor:** Activate the chosen tool with your precise instructions.
        5.  **Analyze Tool Output Critically:** Examine the result returned by the tool.
            * **Success:** Did the tool successfully complete the sub-task? Does the result contain the information needed for the next step or to complete the overall goal? If the overall goal is not yet met, use the result to formulate the instructions for the **next logical step** in your plan.
            * **Partial Success/Info:** Did the tool provide useful information but not complete the sub-task? Use this information to refine your plan or instructions for the next step.
            * **Failure/Error:** Did the tool report an error? Analyze the error message. Can the step be retried with slightly different instructions (e.g., a corrected selector for the browser)? Should a different tool be used? Can the plan be adapted? **Do not give up immediately.** Try to overcome obstacles reasonably.
        6.  **Iterate and Maintain Context:** Repeat steps 2-5, using the results and context from previous steps to inform the next action. Keep track of what has been done and what information has been gathered.
        7.  **Report Progress & Completion:** Briefly explain your chosen action *before* executing a tool. Provide informative updates to the user, especially after a significant step or if encountering difficulties. When the *entire original user request* is fully satisfied, clearly state that the task is complete and provide the final result.\n
        **Important Constraints:**
        - **Use ONLY the provided tools.** Do not perform tasks directly if a tool exists (e.g., don't browse the web yourself, use the `BrowserToolAgent` tool).
        - **Stay Focused:** Adhere strictly to completing the user's request. Do not get sidetracked or perform unrelated actions.
        - **Be Persistent:** Your goal is completion. If a step fails, analyze, adapt, and retry or replan where appropriat.

        Important guidelines:
        - Before starting to search for jobs, check to see if there's additional information you can get from the tools. i.e. historical application data, or user preferences, existing accounts, etc.
        - When searching for jobs, use the user's preferences to filter the results.
        - When interacting with 3rd party websites, ensure that you are using the correct selectors and that the actions you are taking are appropriate for the current state of the page.
        - When login is required, check if the user has an existing account. If they do, use that account. If they don't, create a new account using the user's email address and a secure password.
        - When registering an account on behalf of the user, use the user's email address and a secure password. Make sure to use a tool to store all the information securely.
        - When filling out forms, ensure that all required fields are completed accurately. If a field is not applicable, indicate that it is not applicable. When information is missing, ask the user for clarification, then skip to the next job instaed.
        
        Here is an overview of high-level steps you might take to accomplish the task:
        1. Use the `PlanningAgent` tool to break down the user's request into smaller tasks.
        2. Use the `BrowserToolAgent` tool to search for jobs on the internet. 
        3. Use the `BrowserToolAgent` tool to apply for jobs.
        4. Use the `BrowserToolAgent` tool to check the status of applications.
        5. Use the `BrowserToolAgent` tool to switch between tabs and windows.
        6. Use the `BrowserToolAgent` tool to open gmail and check for emails. For example, account verification emails during registration.
        7. When there are issues with the application process, use the explain to the PlanningAgent what you are trying to do, what happened, and ask it to help you figure out what to do next.
        8. Use the `BrowserToolAgent` tool to check for new job postings.
        """


    ),
        tools=tools_list,
    )