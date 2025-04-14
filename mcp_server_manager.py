# mcp_server_manager.py
# Import BOTH server types
from agents.mcp import MCPServerSse, MCPServerStdio
import asyncio
# Import Union for type hints
from typing import Dict, Any, Optional, Union

# Define a type alias for the union of possible server types for clarity
AnyMCPServer = Union[MCPServerSse, MCPServerStdio]

class MCPServerManager:
    """
    Manages MULTIPLE named MCPServerSse or MCPServerStdio connections concurrently
    using an async context manager, based on YAML configuration.
    """
    def __init__(self, server_configs: Dict[str, Dict[str, Any]]):
        if not isinstance(server_configs, dict):
            raise TypeError(f"Expected server_configs to be a dict, got {type(server_configs)}")

        self._configs = {}
        # Validate configurations upon initialization
        for key, config in server_configs.items():
            if not isinstance(config, dict):
                print(f"WARNING: Config for '{key}' is not a dictionary. Skipping.")
                continue
            server_type = config.get('type')
            params = config.get('params')
            if server_type not in ['sse', 'stdio']:
                print(f"WARNING: MCP Server config '{key}' has missing or invalid 'type'. Must be 'sse' or 'stdio'. Skipping.")
                continue
            if not isinstance(params, dict):
                 print(f"WARNING: MCP Server config '{key}' is missing or has invalid 'params' dictionary. Skipping.")
                 continue
            # Basic check for required params based on type
            if server_type == 'sse' and 'url' not in params:
                 print(f"WARNING: SSE Server '{key}' missing 'url' in 'params'. Skipping.")
                 continue
            if server_type == 'stdio' and 'command' not in params:
                 print(f"WARNING: Stdio Server '{key}' missing 'command' in 'params'. Skipping.")
                 continue

            # If valid, add to internal configs
            self._configs[key] = config

        if len(self._configs) != len(server_configs):
            print("WARNING: Some invalid MCP server configurations were ignored during initialization.")

        self._active_contexts: Dict[str, AnyMCPServer] = {} # Type hint updated
        self._active_servers: Dict[str, AnyMCPServer] = {}  # Type hint updated
        print(f"DEBUG: MCPServerManager initialized for valid servers: {list(self._configs.keys())}")

    async def _connect_server(self, server_key: str, config: Dict[str, Any]):
        """Establishes connection for a single server based on its 'type'."""
        server_type = config['type'] # Type guaranteed by __init__ filter
        server_name = config.get('name', server_key)
        server_params = config['params'] # Params dict guaranteed by __init__ filter

        print(f"INFO: Attempting to connect to MCP Server '{server_key}' ({server_name}) using type '{server_type}'")

        context: Optional[AnyMCPServer] = None

        # --- Instantiate correct class based on 'type' ---
        if server_type == 'sse':
            context = MCPServerSse(name=server_name, params=server_params)
        elif server_type == 'stdio':
            context = MCPServerStdio(name=server_name, params=server_params)
        else:
            # Should not happen if __init__ filtering is correct
            raise ValueError(f"Internal Error: Unknown server type '{server_type}' encountered for '{server_key}'")

        # --- Enter Context (Same logic as before) ---
        try:
            server = await context.__aenter__()
            self._active_contexts[server_key] = context
            self._active_servers[server_key] = server
            print(f"INFO: MCP Server '{server_key}' connection established successfully.")
            return server_key
        except Exception as e:
            print(f"ERROR: Failed connecting to '{server_key}' (Type: {server_type}): {e}")
            try: await context.__aexit__(type(e), e, e.__traceback__)
            except Exception as ae: print(f"ERROR: Exception during cleanup for failed connection '{server_key}': {ae}")
            raise # Re-raise original error

    async def __aenter__(self):
        """Establishes connections to ALL validly configured MCP servers concurrently."""
        if not self._configs:
            print("INFO: MCPServerManager has no valid servers configured, nothing to connect.")
            return self

        print("INFO: MCPServerManager entering context, connecting all configured servers...")
        connect_tasks = [
            self._connect_server(key, config)
            for key, config in self._configs.items() # Iterate over validated configs
        ]

        if not connect_tasks:
             print("INFO: No valid server configurations found to connect to.")
             return self

        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

        failed_servers = []
        attempted_keys = list(self._configs.keys()) # Keys we attempted based on filtered config
        for i, key in enumerate(attempted_keys):
            if i < len(results) and isinstance(results[i], Exception):
                failed_servers.append(key)

        if failed_servers:
            print(f"ERROR: Cleaning up connections due to failures for: {failed_servers}")
            cleanup_task = asyncio.create_task(self.__aexit__(None, None, None))
            await asyncio.sleep(0.1)
            raise ConnectionError(f"Failed to connect to one or more MCP servers: {', '.join(failed_servers)}")

        print(f"INFO: All ({len(self._active_servers)}) configured MCP servers connected successfully.")
        return self

    # --- Update Type Hint for get_server ---
    def get_server(self, server_key: str) -> AnyMCPServer: # Use the Union type alias
        """
        Retrieves a specific active server instance (MCPServerSse or MCPServerStdio)
        by its unique key. Raises KeyError if the server key is invalid or the
        server is not connected.
        """
        if server_key not in self._active_servers:
            available_keys = list(self._active_servers.keys())
            configured_keys = list(self._configs.keys())
            raise KeyError(f"MCP Server '{server_key}' not found or not connected. Configured: {configured_keys}, Currently Active: {available_keys}")
        return self._active_servers[server_key]

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]):
        """Closes connections to ALL active MCP servers sequentially."""
        # ... (No change needed in the sequential __aexit__ logic) ...
        print("INFO: MCPServerManager exiting context, disconnecting all active servers sequentially...")
        if not self._active_contexts: print("INFO: No active MCP server contexts to disconnect."); return False
        disconnection_errors = False
        active_contexts_items = list(self._active_contexts.items())
        for key, context in active_contexts_items:
            print(f"DEBUG: Attempting sequential disconnection for '{key}'...")
            try: await context.__aexit__(exc_type, exc_val, exc_tb); print(f"DEBUG: Server '{key}' disconnected successfully.")
            except Exception as e: print(f"ERROR: Error during sequential disconnection of server '{key}': {e}"); disconnection_errors = True
        active_server_count = len(self._active_servers)
        self._active_contexts.clear(); self._active_servers.clear()
        print(f"INFO: All ({active_server_count}) MCP server contexts cleared.")
        if disconnection_errors: print("WARNING: One or more errors occurred during MCP server disconnection.")
        return False