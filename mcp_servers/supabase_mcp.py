import os
import json
from mcp.server.fastmcp import FastMCP
from supabase import create_client
from dotenv import load_dotenv
from typing import Dict, Any, Optional

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Optional: Default credentials for testing
DEFAULT_EMAIL = os.getenv("DEFAULT_EMAIL", "test@gmail.com")
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "password")

# Global variable to store current user session
current_user_session = None

# Authenticate with Supabase automatically
try:
    # Use default credentials
    user_email = DEFAULT_EMAIL
    user_password = DEFAULT_PASSWORD
    
    # Authenticate with Supabase
    auth_response = supabase.auth.sign_in_with_password({
        "email": user_email,
        "password": user_password
    })
    
    # Store the session for future use
    current_user_session = auth_response.session
    print(f"Successfully authenticated as {auth_response.user.email}")
except Exception as e:
    print(f"Automatic authentication failed: {str(e)}")
    # The MCP will continue to run, but functions requiring authentication will fail

mcp = FastMCP("supabase")

@mcp.tool()
def insert_application(position_title: str, company_name: str) -> Dict[str, Any]:
    """
    Insert a new application record into the applications table.
    
    Args:
        position_title: The title of the position applied for
        company_name: The name of the company applied to
        
    Returns:
        A dictionary with insertion status and application info if successful
    """
    global current_user_session
    
    try:
        # Check if user is authenticated
        if not current_user_session:
            return {
                "success": False,
                "message": "Not authenticated. Authentication is required but failed during initialization."
            }
        
        # Get the current user's ID
        user_id = current_user_session.user.id
        
        # Insert the application into the database
        response = supabase.table("applications").insert({
            "user_id": user_id,
            "position_title": position_title,
            "company_name": company_name
        }).execute()
        
        if response.data and len(response.data) > 0:
            return {
                "success": True,
                "application": response.data[0],
                "message": "Application record created successfully"
            }
        else:
            return {
                "success": False,
                "message": "Failed to create application record"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error creating application record: {str(e)}"
        }

if __name__ == "__main__":
    mcp.run(transport='stdio')
