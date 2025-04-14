# mcp_server_manager.py
# (Code from the previous step, no changes needed for this refactor)
from agents.mcp import MCPServerSse
import asyncio
from typing import Dict, Any, Optional

class MCPServerManager:
    """
    Manages MULTIPLE named MCPServerSse connections concurrently
    using an async context manager.
    """
    def __init__(self, server_configs: Dict[str, Dict[str, Any]]):
        """
        Initializes the manager with configurations for multiple servers.
        :param server_configs: Dict where keys are unique server identifiers
                               and values are dicts of MCPServerSse params (url, name, headers, etc.).
        """
        if not isinstance(server_configs, dict):
             # Ensure input is a dictionary
             raise TypeError(f"Expected server_configs to be a dict, got {type(server_configs)}")

        self._configs = server_configs
        # Stores the MCPServerSse context manager instances
        self._active_contexts: Dict[str, MCPServerSse] = {}
        # Stores the active server instances returned by __aenter__
        self._active_servers: Dict[str, MCPServerSse] = {}
        print(f"DEBUG: MCPServerManager initialized for servers: {list(self._configs.keys())}")

    async def _connect_server(self, server_key: str, config: Dict[str, Any]):
        """Establishes connection for a single server."""
        url = config.get('url')
        if not url:
            print(f"WARNING: Skipping connection for '{server_key}' due to missing URL in config.")
            return None # Indicate skip explicitly

        # Construct params dict for MCPServerSse, ensuring 'url' is included if not top-level
        mcp_params = config.get('params', config).copy() # Prioritize 'params' dict if present
        if 'url' not in mcp_params:
             mcp_params['url'] = url # Ensure URL is in params dict for MCPServerSse

        server_name = config.get('name', server_key) # Use provided name or key as fallback

        print(f"INFO: Attempting to connect to MCP Server '{server_key}' ({server_name}) at {url}")
        context = MCPServerSse(name=server_name, params=mcp_params)

        # Enter the context to establish the connection
        try:
            server = await context.__aenter__()
            self._active_contexts[server_key] = context
            self._active_servers[server_key] = server
            print(f"INFO: MCP Server '{server_key}' connection established successfully.")
            return server_key # Return key on success for tracking
        except Exception as e:
            print(f"ERROR: Failed connecting to '{server_key}': {e}")
            # Attempt cleanup if context was created but __aenter__ failed
            try:
                # Ensure __aexit__ is called even if __aenter__ failed
                await context.__aexit__(type(e), e, e.__traceback__)
            except Exception as ae:
                # Log error during cleanup, but prioritize original error
                print(f"ERROR: Exception during cleanup for failed connection '{server_key}': {ae}")
            raise # Re-raise the original connection error to signal failure

    async def __aenter__(self):
        """Establishes connections to ALL configured MCP servers concurrently."""
        if not self._configs:
            print("INFO: MCPServerManager has no servers configured, nothing to connect.")
            return self # Still return self, manager is active but manages no connections

        print("INFO: MCPServerManager entering context, connecting all configured servers...")
        connect_tasks = [
            # Use asyncio.create_task for slightly better structure if needed, but list comprehension works
            self._connect_server(key, config)
            for key, config in self._configs.items()
            # Ensure we only try to connect those with a URL specified
            if config.get('url')
        ]

        if not connect_tasks:
             print("INFO: No valid server configurations with URLs found to connect to.")
             return self

        # return_exceptions=True allows us to identify which ones failed without stopping others
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

        # Check for any connection failures
        failed_servers = []
        # Iterate through the original keys we *attempted* to connect
        attempted_keys = [key for key, conf in self._configs.items() if conf.get('url')]
        for i, key in enumerate(attempted_keys):
            if isinstance(results[i], Exception):
                # Error should have been logged in _connect_server
                failed_servers.append(key)

        if failed_servers:
            print(f"ERROR: Cleaning up connections due to failures for: {failed_servers}")
            # Attempt to clean up any servers that *did* connect successfully in this failed attempt
            # Create a separate task for cleanup so we can raise the error promptly
            cleanup_task = asyncio.create_task(self.__aexit__(None, None, None))
            await asyncio.sleep(0.1) # Give cleanup a moment to start
            raise ConnectionError(f"Failed to connect to one or more MCP servers: {', '.join(failed_servers)}")

        print(f"INFO: All ({len(self._active_servers)}) configured MCP servers connected successfully.")
        return self # Return the manager instance itself

    def get_server(self, server_key: str) -> MCPServerSse:
        """
        Retrieves a specific active server instance by its unique key.
        Raises KeyError if the server key is invalid or the server is not connected.
        """
        if server_key not in self._active_servers:
            available_keys = list(self._active_servers.keys())
            configured_keys = list(self._configs.keys())
            raise KeyError(f"MCP Server '{server_key}' not found or not connected. Configured: {configured_keys}, Currently Active: {available_keys}")
        return self._active_servers[server_key]

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]):
        """Closes connections to ALL active MCP servers sequentially."""
        print("INFO: MCPServerManager exiting context, disconnecting all active servers sequentially...")
        if not self._active_contexts:
            print("INFO: No active MCP server contexts to disconnect.")
            return False # Nothing to do

        disconnection_errors = False
        # Use items() to iterate safely while potentially modifying dict indirectly later (clear)
        active_contexts_items = list(self._active_contexts.items())

        for key, context in active_contexts_items:
            print(f"DEBUG: Attempting sequential disconnection for '{key}'...")
            try:
                # Await __aexit__ directly for each context
                await context.__aexit__(exc_type, exc_val, exc_tb)
                print(f"DEBUG: Server '{key}' disconnected successfully.")
            except Exception as e:
                print(f"ERROR: Error during sequential disconnection of server '{key}': {e}")
                disconnection_errors = True
                # Decide if one failure should stop others? Probably not for cleanup.

        # Clear internal state after attempting all disconnections
        active_server_count = len(self._active_servers)
        self._active_contexts.clear()
        self._active_servers.clear()
        print(f"INFO: All ({active_server_count}) MCP server contexts cleared.")

        # If disconnection errors occurred, maybe log differently or raise specific cleanup error?
        if disconnection_errors:
            print("WARNING: One or more errors occurred during MCP server disconnection.")

        # Return False to propagate exceptions from within the 'with' block.
        return False