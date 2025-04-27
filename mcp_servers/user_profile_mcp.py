import os
import json
import requests
import base64
import tempfile
import fitz  # PyMuPDF for PDF to image conversion
from openai import OpenAI
from mcp.server.fastmcp import FastMCP
from supabase import create_client
from dotenv import load_dotenv
from typing import Dict, Any, Optional
import re # Added for sanitizing filename

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

user_email = DEFAULT_EMAIL
user_password = DEFAULT_PASSWORD

# Authenticate with Supabase
auth_response = supabase.auth.sign_in_with_password({
    "email": user_email,
    "password": user_password
})

user_id = auth_response.user.id
user_email = auth_response.user.email

# Store the session for future use
current_user_session = auth_response.session

mcp = FastMCP("user_profile")

# @mcp.tool()
def authenticate(email: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    """
    Authenticate with Supabase to enable retrieving the current user's profile.
    
    Args:
        email: The user's email (defaults to DEFAULT_EMAIL if not provided)
        password: The user's password (defaults to DEFAULT_PASSWORD if not provided)
        
    Returns:
        A dictionary with authentication status and user info if successful
    """
    global current_user_session
    
    try:
        # Use provided credentials or defaults
        user_email = email or DEFAULT_EMAIL
        user_password = password or DEFAULT_PASSWORD
        
        # Authenticate with Supabase
        auth_response = supabase.auth.sign_in_with_password({
            "email": user_email,
            "password": user_password
        })
        
        # Store the session for future use
        current_user_session = auth_response.session
        
        return {
            "success": True,
            "user_id": auth_response.user.id,
            "email": auth_response.user.email,
            "message": "Authentication successful"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Authentication failed: {str(e)}"
        }

@mcp.tool()
def get_current_user_profile() -> Dict[str, Any]:
    """
    Retrieve the profile of the currently authenticated user.
    Must call authenticate() first.
    
    Returns:
        A dictionary containing the current user's profile information
    """
    global current_user_session
    
    if not current_user_session:
        return {
            "success": False,
            "message": "Not authenticated. Call authenticate() first."
        }
    
    try:
        # Get the current user's ID
        user_id = current_user_session.user.id
        
        # Fetch the profile using the existing get_user_profile function
        return get_user_profile()
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving current user profile: {str(e)}"
        }

# Helper function to sanitize filename
def sanitize_filename(name: str) -> str:
    # Remove invalid characters and replace spaces with underscores
    name = re.sub(r'[\/*?":<>|]', '', name) # Remove invalid chars
    name = re.sub(r'\s+', '_', name) # Replace spaces with underscore
    return name

@mcp.tool()
def get_resume_path() -> Dict[str, Any]:
    """
    Retrieve the user's resume URL, download it, and save it locally 
    with a stable, professional filename.
    
    Args:
        user_id: The ID of the user whose resume to retrieve
        
    Returns:
        A dictionary containing the local resume path and status information
    """
    # --- Get User's Full Name --- 
    name_info = get_full_name() # Call existing tool internally
    user_full_name = "User"
    if name_info.get("success") and name_info.get("full_name"):
        user_full_name = name_info["full_name"]
    sanitized_name = sanitize_filename(user_full_name)
    
    # --- Define Download Path --- 
    # Ensure a directory exists for downloads (e.g., in the service's CWD)
    download_dir = os.path.join(os.getcwd(), "resume_downloads")
    os.makedirs(download_dir, exist_ok=True)
    # Construct the stable filename
    stable_filename = f"{sanitized_name}_Resume.pdf"
    local_resume_path = os.path.join(download_dir, stable_filename)
    print(f"DEBUG: Target local resume path: {local_resume_path}")

    try:
        # --- Query Resume URL --- 
        print(f"DEBUG: Querying resume URL for user_id: {user_id}")
        response_url = supabase.table("profiles").select("resume_url").eq("user_id", user_id).execute()
        
        if not response_url.data or len(response_url.data) == 0:
             return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }

        resume_url = response_url.data[0].get("resume_url")
        if not resume_url:
            return {
                "success": False,
                "message": "No resume URL found for this user in profile"
            }
        
        print(f"DEBUG: Found resume URL: {resume_url}")

        # --- Download Resume --- 
        print(f"DEBUG: Downloading resume from {resume_url}...")
        response_download = requests.get(resume_url, stream=True) # Use stream=True for potentially large files
        response_download.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        
        # --- Save Resume Locally --- 
        print(f"DEBUG: Saving resume to {local_resume_path}...")
        with open(local_resume_path, 'wb') as f:
            for chunk in response_download.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"DEBUG: Resume saved successfully.")

        # --- Return Success --- 
        return {
            "success": True,
            "resume_path": local_resume_path, # Return the stable path
            "resume_url": resume_url, # Still useful to return the original URL
            "message": "Resume downloaded and saved successfully with stable name."
        }
            
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to download resume from URL {resume_url}: {e}")
        return {
            "success": False,
            "message": f"Failed to download resume: {str(e)}"
        }
    except IOError as e:
        print(f"ERROR: Failed to save resume to {local_resume_path}: {e}")
        return {
            "success": False,
            "message": f"Failed to save downloaded resume: {str(e)}"
        }
    except Exception as e:
        print(f"ERROR: Unexpected error retrieving resume path: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"Error retrieving resume: {str(e)}"
        }

@mcp.tool()
def get_full_name() -> Dict[str, Any]:
    """
    Retrieve the user's first and last name from the Supabase profile table.
    
    Args:
        user_id: The ID of the user whose name to retrieve
        
    Returns:
        A dictionary containing the user's full name and status information
    """
    try:
        # Query the user's profile from the database
        response = supabase.table("profiles").select("first_name, last_name").eq("user_id", user_id).execute()
        
        if response.data and len(response.data) > 0:
            first_name = response.data[0].get("first_name", "")
            last_name = response.data[0].get("last_name", "")
            
            if first_name or last_name:
                full_name = f"{first_name} {last_name}".strip()
                return {
                    "success": True,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "message": "Name retrieved successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "User has no name information"
                }
        else:
            return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving name: {str(e)}"
        }

@mcp.tool()
def get_user_profile() -> Dict[str, Any]:
    """
    Retrieve the complete user profile from Supabase.
    
    Args:
        user_id: The ID of the user whose profile to retrieve
        
    Returns:
        A dictionary containing the complete user profile information
    """
    try:
        # Query the user's complete profile from the database
        response = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        
        if response.data and len(response.data) > 0:
            profile_data = response.data[0]
            return {
                "success": True,
                "profile": profile_data,
                "message": "User profile retrieved successfully"
            }
        else:
            return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving user profile: {str(e)}"
        }

@mcp.tool()
def get_resume_content() -> Dict[str, Any]:
    """
    Fetch the user's resume content directly from the resume_text column in the profiles table.
    
    Args:
        user_id: The ID of the user whose resume content to retrieve
        
    Returns:
        A dictionary containing the resume content and status information
    """
    try:
        # Query the user's profile from the database to get resume_text
        response = supabase.table("profiles").select("resume_text").eq("user_id", user_id).execute()
        
        if response.data and len(response.data) > 0:
            resume_text = response.data[0].get("resume_text")
            if resume_text:
                return {
                    "success": True,
                    "resume_content": resume_text,
                    "message": "Resume content retrieved successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "No resume text found for this user"
                }
        else:
            return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving resume content: {str(e)}"
        }

# @mcp.tool()
def get_application_details() -> Dict[str, Any]:
    """
    Retrieve comprehensive application details to minimize missing information issues.
    Collects all available profile data and application preferences.
    
    Returns:
        Dictionary with all available user information for job applications
    """
    try:
        # Query the user's complete profile
        response = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        
        if not response.data or len(response.data) == 0:
            return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }
            
        profile = response.data[0]
        
        # Get additional application preferences if available
        # Note: You may need to create this table in your Supabase database
        # pref_response = supabase.table("application_preferences").select("*").eq("user_id", user_id).execute()
        # preferences = pref_response.data[0] if pref_response.data and len(pref_response.data) > 0 else {}
        
        # Get education information
        edu_response = supabase.table("education").select("*").eq("user_id", user_id).execute()
        education = edu_response.data if edu_response.data else []
        
        # Get work experience
        exp_response = supabase.table("experience").select("*").eq("user_id", user_id).execute()
        experience = exp_response.data if exp_response.data else []
        
        # Get skills
        skills_response = supabase.table("skills").select("*").eq("user_id", user_id).execute()
        skills = skills_response.data if skills_response.data else []
        
        # Combine all available information for applications
        application_data = {
            "profile": profile,
            # "preferences": preferences,
            "education": education,
            "experience": experience,
            "skills": skills,
            "available_fields": [key for key in profile if profile[key] is not None]
        }
        
        return {
            "success": True,
            "application_data": application_data,
            "message": "Application details retrieved successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving application details: {str(e)}"
        }

if __name__ == "__main__":
    mcp.run(transport='stdio')

    # # get resume_path()

    # supabase_url = os.getenv("SUPABASE_URL")
    # supabase_key = os.getenv("SUPABASE_KEY")
    # supabase = create_client(supabase_url, supabase_key)

    # # Authenticate with Supabase
    # auth_response = supabase.auth.sign_in_with_password({
    #     "email": DEFAULT_EMAIL,
    #     "password": DEFAULT_PASSWORD
    # })
    # user_id = auth_response.user.id
    # user_email = auth_response.user.email

    # # Store the session for future use
    # current_user_session = auth_response.session
    # print(f"Authenticated as {user_email} with user ID {user_id}")

    # # Test the functions
    # auth_result = authenticate(user_email, user_password)
    # print(f"Authentication result: {auth_result}")

    # profile_result = get_current_user_profile()
    # print(f"Profile result: {profile_result}")

    # resume_result = get_resume_path()
    # print(f"Resume result: {resume_result}")

    # name_result = get_full_name()
    # print(f"Name result: {name_result}")

    # user_profile_result = get_user_profile()
    # print(f"User profile result: {user_profile_result}")

    # resume_content_result = get_resume_content()
    # print(f"Resume content result: {resume_content_result}")

    # # mcp.run(transport='stdio')