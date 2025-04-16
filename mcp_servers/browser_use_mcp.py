import asyncio
import os
import sys
from typing import Optional, Any # Use specific types if known

# Add project root if necessary
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("browser_tool_service")

# Apply nest_asyncio early IF NEEDED (e.g., for environments like Spyder/Jupyter)
# It might be less critical now that AnyIO manages the final loop, but can prevent
# issues if other async code runs unexpectedly before the main setup.
try:
    import nest_asyncio
    nest_asyncio.apply()
    print("Applied nest_asyncio.")
except ImportError:
    pass # Not installed or not needed

load_dotenv()

# --- Global Variables for Shared State ---
shared_browser: Optional[Browser] = None
shared_context: Optional[Any] = None
llm_instance: Optional[ChatOpenAI] = None

# --- Configuration ---
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" # Or get from env
OPENAI_MODEL = "gpt-4o"

async def setup_mcp_and_browser():
    """Initializes MCP, LLM, Browser, and Browser Context."""
    global shared_browser, shared_context, llm_instance

    # No need to check for existing mcp here, as this runs only once on startup
    print("Initializing FastMCP...")


    print(f"Initializing LLM ({OPENAI_MODEL})...")
    llm_instance = ChatOpenAI(model=OPENAI_MODEL)

    print("Initializing Browser...")
    try:
        browser_config = BrowserConfig(
            chrome_instance_path=CHROME_PATH,
            disable_security=True,
        )
        shared_browser = Browser(config=browser_config)
        print("Initializing Browser Context...")
        shared_context = await shared_browser.new_context()
        print("Browser and Context Initialized Successfully.")
    except Exception as e:
        print(f"FATAL: Failed to initialize browser or context: {e}")
        raise # Re-raise to stop the script

    print("Registering MCP tools...")
    # Tool registration happens when the decorated function below is defined.


# --- MCP Tool Definition ---
# This function needs to be defined *before* mcp.run is called,
# but it relies on the globals being set by setup_mcp_and_browser.
@mcp.tool()
async def browser_use(task: str) -> Any:
    """
    Uses a browser agent to perform a given task, returning extracted content.
    Assumes setup_mcp_and_browser() has successfully run.
    """
    print(f"\n>>> Received browser_use task: {task}")
    if shared_context is None or llm_instance is None or shared_browser is None:
        error_msg = "ERROR: Browser/LLM state not initialized. Cannot run task."
        print(error_msg)
        return error_msg

    try:
        agent = Agent(
            task=task,
            llm=llm_instance,
            browser_context=shared_context,
            browser=shared_browser,
        )
        print(f"Running agent for task: {task}...")
        result_data = await agent.run()
        print("Agent finished.")

        extracted_content = "No content extracted."
        if (result_data and hasattr(result_data, 'history') and result_data.history and
            hasattr(result_data.history[-1], 'result') and result_data.history[-1].result and
            hasattr(result_data.history[-1].result[-1], 'extracted_content')):
            extracted_content = result_data.history[-1].result[-1].extracted_content
            print(f"Extracted content: {extracted_content}")
        else:
            print("Warning: Could not find expected extracted_content in agent result structure.")
            # extracted_content = str(result_data) # Optional fallback

        return extracted_content

    except Exception as e:
        error_msg = f"ERROR: Exception during agent execution for task '{task}': {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return error_msg


# --- Main Execution Block ---
if __name__ == "__main__":
    # 1. Run the ASYNCHRONOUS setup tasks first
    print("--- Running initial async setup ---")
    try:
        # Use asyncio.run() ONLY for the setup coroutine
        asyncio.run(setup_mcp_and_browser())
        print("--- Async setup complete ---")
    except Exception as setup_error:
        print(f"FATAL: Exiting due to setup error: {setup_error}")
        sys.exit(1) # Exit if setup fails

    # Ensure MCP was initialized by setup
    if mcp is None:
        print("FATAL: MCP instance was not created during setup. Exiting.")
        sys.exit(1)

    # 2. Start the MCP server - This is SYNCHRONOUS and starts its OWN event loop (via AnyIO)
    print("--- Starting MCP server with stdio transport ---")
    # This call will block until the server is stopped (e.g., Ctrl+C)
    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        print("\n--- Server stopped by user (KeyboardInterrupt) ---")
    except Exception as run_error:
        print(f"\n--- MCP server exited with error: {run_error} ---")
    finally:
        print("--- Server process finished ---")
        # NOTE: Graceful async cleanup of browser resources is difficult here
        # because we are outside the async context managed by asyncio.run(setup...).
        # Process termination usually handles cleanup, but explicit closure isn't easily done.