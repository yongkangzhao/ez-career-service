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

@mcp.tool()
def get_resume_path() -> Dict[str, Any]:
    """
    Retrieve the user's resume URL from the Supabase profile table.
    
    Args:
        user_id: The ID of the user whose resume to retrieve
        
    Returns:
        A dictionary containing the resume URL and status information
    """
    try:
        # Query the user's profile from the database
        response = supabase.table("profiles").select("resume_url").eq("user_id", user_id).execute()
        
        if response.data and len(response.data) > 0:
            resume_url = response.data[0].get("resume_url")
            if resume_url:
                # download the resume file
                # save it to a temporary location
                # return the resume path

                #download the resume file
                response = requests.get(resume_url)
                if response.status_code != 200:
                    return {
                        "success": False,
                        "message": f"Failed to download resume: HTTP {response.status_code}"
                    }
                # Save PDF to a temporary file that will be persisted with meaningful name
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                # Return the resume URL
                # Clean up the temporary file

                return {
                    "success": True,
                    "resume_path": temp_file_path,
                    "resume_url": resume_url,
                    "message": "Resume URL retrieved successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "No resume found for this user"
                }
        else:
            return {
                "success": False,
                "message": f"No profile found for user ID: {user_id}"
            }
    except Exception as e:
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
    Fetch the user's resume, convert it to image, analyze with GPT-4o,
    and return a structured text representation of the resume content.
    
    Args:
        user_id: The ID of the user whose resume content to analyze
        
    Returns:
        A dictionary containing the structured resume content and status information
    """
    # Initialize OpenAI client
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        return {
            "success": False,
            "message": "OPENAI_API_KEY environment variable not set"
        }
    
    client = OpenAI(api_key=openai_api_key)
    
    try:
        # First, get the resume URL
        resume_result = get_resume_path()
        
        if not resume_result.get("success"):
            return resume_result  # Return the error from get_resume
        
        resume_url = resume_result.get("resume_url")
        
        # Download the PDF file
        response = requests.get(resume_url)
        if response.status_code != 200:
            return {
                "success": False,
                "message": f"Failed to download resume: HTTP {response.status_code}"
            }
        
        # Save PDF to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name
        
        try:
            # Open the PDF with PyMuPDF
            pdf_document = fitz.open(temp_file_path)
            
            # Convert pages to images
            base64_images = []
            for page_num in range(min(len(pdf_document), 5)):  # Limit to 5 pages max
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Higher resolution
                img_data = pix.tobytes("png")
                base64_image = base64.b64encode(img_data).decode('utf-8')
                base64_images.append(base64_image)
            
            # Close the PDF
            pdf_document.close()
            
            # If we have images, send them to GPT-4o
            if base64_images:
                # Prepare messages for GPT-4o
                messages = [
                    {
                        "role": "system", 
                        "content": "You are an expert at parsing resumes. Extract all relevant information from this resume image and organize it into a structured format with sections for: personal information, education, work experience, skills, certifications, projects, and any other relevant categories. Maintain the hierarchical structure of the resume in your response and ensure all dates, titles, and details are accurately captured."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Parse this resume and return the structured content:"}
                        ]
                    }
                ]
                
                # Add images to the user message
                for i, img in enumerate(base64_images):
                    messages[1]["content"].append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img}",
                            "detail": "high"
                        }
                    })
                
                # Call GPT-4o to analyze the resume
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=4000,
                    temperature=0.0,
                )
                
                resume_content = response.choices[0].message.content
                
                return {
                    "success": True,
                    "resume_content": resume_content,
                    "message": "Resume parsed successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "Could not extract images from the PDF"
                }
                
        finally:
            # Clean up the temporary file
            os.unlink(temp_file_path)
            
    except Exception as e:
        return {
            "success": False,
            "message": f"Error processing resume: {str(e)}"
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