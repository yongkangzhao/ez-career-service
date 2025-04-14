# EZ-Career: Automated Job Application Service (Backend)

## Overview

Tired of the endless grind of finding and applying for jobs in competitive markets like Silicon Valley and beyond? **EZ-Career** introduces a **state-of-the-art backend service** designed to power an **autonomous job application system**. Forget manual searching and tedious form-filling – leverage the power of collaborative AI agents to manage your job hunt efficiently, reduce stress, and put your application process on easy mode!

At its core, this service employs a sophisticated **multi-agent architecture**. Instead of a single monolithic AI, it utilizes a team of specialized agents, each expert in a specific domain, working together to achieve complex goals:

* **Browser Agents:** Intelligently navigate complex job boards and application portals (like LinkedIn, Google Careers, Indeed), interact precisely with web elements, and fill out forms accurately. This grounding in real-world action is achieved via the **Message Control Protocol (MCP)** connecting to tools like Playwright.
* **Planning Agents:** Analyze high-level user goals (e.g., "find Senior ML Engineer roles in Milpitas matching my resume") and exhibit **dynamic planning capabilities**. They devise multi-step strategies, breaking down the task into logical sub-goals executable by other specialized agents.
* *(Future Agents):* The architecture is designed for extension with agents specializing in Resume Parsing (understanding your unique skills), Cover Letter Generation (tailoring applications), interaction with specific Job Board APIs, Application Tracking, and more!

The system's power lies in its **dynamic orchestration**. An intelligent orchestrator agent assesses the current task, context, and available agent capabilities, dynamically selecting and sequencing the appropriate "tool agent" – implementing the powerful **Agent-as-Tool** pattern. This allows for flexible, adaptive, and robust workflows far beyond simple automation scripts.

Built on a modern, high-performance stack including **FastAPI** (for asynchronous API handling) and **asyncio**, the service is engineered for scalability and concurrent operation. Configuration of agents and critical infrastructure like multiple, distinct MCP server connections is managed centrally and easily through a **declarative YAML file (`agents_config.yaml`)**, allowing for rapid extension and customization without deep code modifications for standard agent types.

While currently establishing the core multi-agent framework, orchestration logic, and MCP integration, the vision includes robust **database integration** (for managing user profiles, job data, application status) and seamless interaction with a dedicated **frontend user interface** (developed in a separate repository). This backend provides the intelligent, adaptable engine for a truly automated and simplified job application experience.

## Features

* **FastAPI Backend:** Modern, asynchronous Python web server.
* **Centralized YAML Configuration:** Define MCP servers and agent parameters in `agents_config.yaml`.
* **Multi-MCP Server Support:** Manage connections to diverse MCP servers concurrently.
* **Dynamic Agent Loading:** Agents defined in YAML are loaded automatically on startup.
* **Generic Agent Creation:** Instantiates standard `Agent` objects from YAML config.
* **Multi-Agent System:** Utilizes specialized agents working collaboratively.
* **Dynamic Planning & Orchestration:** Orchestrator agent dynamically selects and sequences tool agents.
* **Agent-as-Tool Pattern:** Enables modular and composable agent capabilities.
* **Asynchronous Operation:** Built on `asyncio` for efficiency.
* **Lifecycle Management:** Handles MCP connections during FastAPI startup/shutdown.
* **Dependency Management:** Uses `pyproject.toml` and `uv.lock` (managed via `uv`).
* **Health Check:** `/health` endpoint for service monitoring.
* **Extensible Design:** Built for future additions like databases and more specialized agents.

## Prerequisites & Setup

### 1. Core Software

* **Python:** Version 3.12 or higher (check `pyproject.toml`).
* **uv:** Recommended Python package manager (`pip install uv`).
* **Node.js & npm:** Required for `npx` to run the Playwright MCP server.
  * Install Node.js (LTS recommended) from [https://nodejs.org/](https://nodejs.org/). `npm` is included.
  * Verify: `node -v && npm -v`.
* **Google Chrome:** Required for the Playwright MCP server to interact with websites.
* **Git:** (Optional) For cloning the repository.

### 2. Project Installation

1. **Clone/Download:** Get the project files.

    ```bash
    cd ez-career-service
    ```

2. **Create & Activate Virtual Environment (using `uv`):**

    ```bash
    uv venv
    source .venv/bin/activate # Linux/macOS (or equivalent)
    ```

3. **Install Python Dependencies (using `uv`):**

    ```bash
    uv pip install .
    ```

    *(Ensure `PyYAML>=6.0` is listed in `pyproject.toml` dependencies).*

### 3. Configure `agents_config.yaml`

This file defines the infrastructure and agents.

* **`mcp_servers`**: Define necessary MCP servers (like `playwright_mcp`). Ensure the `url` (e.g., `http://localhost:8931/sse`) matches the port the server will run on.
* **`agents`**: Define agents like `BrowserToolAgent` (for web interaction), `PlanningAgent` (for strategy), or future agents. Set `mcp_server_key` for agents needing browser/device control. Configure `parameters` (`instructions`, `model_settings`, `handoff_description`).

### 4. Running Required MCP Servers (Example: Playwright for Web Interaction)

If your `agents_config.yaml` defines agents requiring MCP servers (like `playwright_mcp`), you **must** start these servers *before* starting the FastAPI application.

**A. Start Chrome in Remote Debugging (CDP) Mode:**

* **IMPORTANT:** Ensure all other instances of Google Chrome are **completely closed** before running this command.
  * Open your terminal and run the command appropriate for your Operating System. You might need to adjust the path to your Chrome executable:

    * **On macOS:**

         ```bash
         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222
         ```

    * **On Linux:** (Path may vary)

         ```bash
         google-chrome --remote-debugging-port=9222
         # or chromium-browser --remote-debugging-port=9222
         ```

    * **On Windows:** (Path may vary)

         ```bash
         "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
         # Or "C:\Program Files (x86)\..."
         ```

  * This will launch Chrome. Look in the **terminal output** where you ran the command. You should see a line like:
        `DevTools listening on ws://127.0.0.1:9222/devtools/browser/SOME-UNIQUE-ID`
  * **Copy this entire `ws://...` URL.** You will need it for the next step. The `SOME-UNIQUE-ID` part changes every time.

**B. Start the Playwright MCP Server:**

* Open **a new terminal window** (leave the one running Chrome CDP open).
  * Run the following `npx` command, replacing `<PASTE_YOUR_CDP_ENDPOINT_URL_HERE>` with the full `ws://...` URL you copied from the Chrome terminal output:

       ```bash
       npx @playwright/mcp@latest --port 8931 --cdp-endpoint <PASTE_YOUR_CDP_ENDPOINT_URL_HERE>
       ```

  * Ensure `--port 8931` specifies the port the MCP server will listen on. This **must match** the port in the `url` specified for `playwright_mcp` in your `agents_config.yaml`.
  * Leave this terminal running. It is now acting as the bridge between the agent framework and the browser.

*(Repeat similar steps for any other MCP servers defined in your config, following their specific startup instructions).*

## Running the Service

1. **Prerequisites:** Ensure Python venv is active, dependencies installed, and required MCP servers are running.
2. **Start FastAPI Service:**

    ```bash
    # Development (auto-reload)
    uvicorn api:app --reload --host 0.0.0.0 --port 8000

    # Production
    # uvicorn api:app --host 0.0.0.0 --port 8000
    ```

    The application will start, connect to MCP servers, load agents, and create the orchestrator.

## Order of Operations & Reconnection

1. Start Chrome (CDP Mode).
2. Start Playwright MCP Server (connected to Chrome).
3. Start this FastAPI application (`uvicorn api:app ...`).

**Important:** If the connection between the FastAPI service and an MCP server breaks *after* the application has started, this current setup **requires the FastAPI application to be restarted** to re-establish the connection during its startup phase.

## Using the API

API Docs available at `http://localhost:8000/docs`.

### 1. Orchestrate Job Application Task

* **Endpoint:** `/orchestrate`
* **Method:** `POST`
* **Request Body (JSON):** Describe the job application task.

    ```json
    {
      "task": "Find Machine Learning Engineer roles in California on LinkedIn and apply to the top 3 using my profile."
    }
    ```

* **Success Response (200 OK):** Returns the final status or result from the orchestrator.

    ```json
    {
      "result": "Applied to 3 roles: [Role 1], [Role 2], [Role 3]. View status in dashboard.",
      "trace_id": "trace_..."
    }
    ```

    *(Note: Actual result depends heavily on the capabilities of the configured agents).*
* **Example (`curl`):**

    ```bash
    curl -X 'POST' \
    'http://0.0.0.0:8000/orchestrate' \
    -H 'accept: application/json' \
    -H 'Content-Type: application/json' \
    -d '{
    "task": "search for MLE Remote jobs on linkedin and apply to ones that supports easy apply, do not stop until you have successfully submit an application, when you encounter problems, try your best to adapt, plan what you want to do first."
    }'
    ```

### 2. Health Check

* **Endpoint:** `/health`
* **Method:** `GET`
* **Success Response (200 OK):** Shows service status details.
* **Example (`curl`):** `curl http://localhost:8000/health`

## Project Structure Notes

* **Backend Focus:** This repository contains the EZ-Career backend service API.
* **Frontend:** A separate repository will house the frontend user interface that interacts with this API.
* **`api.py`**: Main FastAPI application.
* **`agents_config.yaml`**: Central configuration.
* **`mcp_server_manager.py`**: Manages MCP server connections.
* **`tool_agents/`**: Contains agent-related code (currently orchestrator factory).

## Adding New Tool Agents

The system is designed for easy extension:

1. **Define Agent in YAML:** Add a new entry to the `agents` list in `agents_config.yaml`.
    * Provide `name`, `parameters` (`instructions`, `model_settings`, `handoff_description`).
    * If it needs browser/device control (MCP), define the required server in `mcp_servers` (if new) and reference its key using `mcp_server_key`.
    * *Examples*: Add a `ResumeParserAgent` (no MCP) or a `LinkedInInteractionAgent` (needs `playwright_mcp`).
2. **Restart Service:** Restart the FastAPI service (`uvicorn`). Ensure any *new* required MCP servers are started first.

*(This assumes the new agent fits the standard `Agent` initialization model handled by the generic creator in `api.py`. For agents requiring custom Python logic or state, specific factory functions or Agent subclasses might be needed, requiring adjustments to the loading logic.)*

## Future Work / Roadmap

* **Database Integration:** Implement database (e.g., PostgreSQL, MongoDB) for user profiles, job details, application tracking.
* **Specialized Agents:** Develop agents for Resume Parsing, Cover Letter Generation, Job Board Scraping (LinkedIn, Indeed, etc.), Application Status Checking, Secure Credential Management, Form Filling, Cover Letter Generation, and more.
* **API Expansion:** Add endpoints for managing user profiles, viewing application status, finer-grained task control.
* **Frontend Integration:** Connect backend to the dedicated frontend repository.
* **Robustness & Scalability:** Enhance error handling, recovery, state management for long workflows, and optimize for higher throughput.
