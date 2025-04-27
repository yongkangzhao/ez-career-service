import os
from mcp.server.fastmcp import FastMCP
from supabase import create_client, PostgrestAPIError
from dotenv import load_dotenv
from typing import Dict, Any, Optional
import logging
import sys
import traceback
import uuid
from datetime import datetime
from sentence_transformers import SentenceTransformer

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("user_assistance_mcp_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("user_assistance_mcp")

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

logger.info(f"Initializing with SUPABASE_URL: {supabase_url and 'SET' or 'NOT SET'}")
logger.info(f"Initializing with SUPABASE_KEY: {supabase_key and 'SET' or 'NOT SET'}")

if not supabase_url or not supabase_key:
    logger.error("Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_KEY in .env file.")
    # Continue anyway to prevent startup failure, but log detailed warnings

try:
    supabase = create_client(supabase_url or "", supabase_key or "")
    logger.info("Supabase client created successfully")
except Exception as e:
    logger.error(f"Failed to create Supabase client: {e}")
    logger.error(traceback.format_exc())
    # Create a dummy client to prevent startup errors
    from unittest.mock import MagicMock
    supabase = MagicMock()
    logger.warning("Using mock Supabase client due to initialization error")

mcp = FastMCP("user_assistance")
logger.info("FastMCP initialized for user_assistance")

# Initialize Sentence Transformer model
# Using gte-small as requested, which produces 384 dimensions
# This might take a moment on first run as the model downloads
try:
    logger.info("Loading sentence-transformer model: thenlper/gte-small")
    embedding_model_st = SentenceTransformer('thenlper/gte-small')
    logger.info("Sentence-transformer model loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load sentence-transformer model: {e}")
    embedding_model_st = None # Set to None if loading fails

# Default user ID - attempt to get the user ID from the user_profile_mcp
DEFAULT_USER_ID = None
DEFAULT_EMAIL = os.getenv("DEFAULT_EMAIL", "test@gmail.com")
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "password")

try:
    auth_response = supabase.auth.sign_in_with_password({
        "email": DEFAULT_EMAIL,
        "password": DEFAULT_PASSWORD
    })
    DEFAULT_USER_ID = auth_response.user.id
    logger.info(f"Successfully authenticated with default credentials, user ID: {DEFAULT_USER_ID}")
except Exception as e:
    logger.error(f"Failed to authenticate with default credentials: {e}")
    logger.error(traceback.format_exc())
    # Fall back to a static ID if we can't get one from auth
    DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"
    logger.warning(f"Using fallback user ID: {DEFAULT_USER_ID}")

@mcp.tool()
def get_current_user_id() -> Dict[str, Any]:
    """
    Get the current user ID (helpful for other functions that require user_id)
    
    Returns:
        Dictionary with the current user ID
    """
    logger.info(f"get_current_user_id called, returning: {DEFAULT_USER_ID}")
    
    return {
        "success": True,
        "user_id": DEFAULT_USER_ID,
        "message": "Current user ID retrieved successfully"
    }

@mcp.tool()
def log_application_issue(
    user_id: str,
    application_id: str,
    company: str, 
    position: str,
    issue_type: str,
    issue_details: str
) -> Dict[str, Any]:
    """
    Log an issue encountered during the job application process.
    Ensures a basic application record exists before logging the issue.
    The agent will continue with other applications and not wait for resolution.
    
    Args:
        user_id: User's ID
        application_id: ID of the application
        company: Company name
        position: Position title
        issue_type: Type of issue (e.g., "Missing Information", "Decision Required")
        issue_details: Detailed description of the issue
        
    Returns:
        Dictionary with issue ID and status
    """
    logger.info(f"log_application_issue called with: user_id={user_id}, application_id={application_id}, company={company}, position={position}, issue_type={issue_type}")
    logger.info(f"Issue details: {issue_details}")
    
    try:
        # # Step 1: Ensure a basic application record exists to satisfy foreign key
        # logger.debug(f"Upserting basic application record for application_id: {application_id}")
        # app_upsert_data = {
        #     "id": application_id, # Primary key for upsert
        #     "user_id": user_id,
        #     "company_name": company,
        #     "position_title": position,
        #     "status": "applied", # Changed from "issue_logged" to "applied" to match schema constraints
        #     "created_at": datetime.now().isoformat(),
        #     "notes": f"Auto-generated entry for issue logging: {issue_type}. {issue_details}" # Adding notes to help identify these auto-created entries
        # }
        # try:
        #     # Use upsert to either insert or ignore if exists (based on PK 'id')
        #     supabase.table("applications").upsert(app_upsert_data).execute()
        #     logger.debug(f"Successfully upserted application record for {application_id}")
        # except PostgrestAPIError as app_e:
        #     # Log error but proceed to log the issue anyway if possible
        #     logger.error(f"Error upserting application record for {application_id}: {app_e}")
        #     logger.error(traceback.format_exc())
        # except Exception as app_e_gen:
        #     logger.error(f"Unexpected error upserting application record for {application_id}: {app_e_gen}")
        #     logger.error(traceback.format_exc())

        # Step 2: Log the specific issue
        logger.debug("Preparing to insert issue into application_issues table")
        issue_insert_data = {
            "user_id": user_id,
            "application_id": application_id,
            "company": company,
            "position": position,
            "issue_type": issue_type,
            "issue_details": issue_details,
            "status": "pending", # Status of the issue itself
            "created_at": datetime.now().isoformat(),
        }
        logger.debug(f"Issue Insert data: {issue_insert_data}")
        
        logger.debug("Executing supabase insert for application_issues")
        response = supabase.table("application_issues").insert(issue_insert_data).execute()
        logger.debug(f"Supabase application_issues response: {response}")
        
        if response.data and len(response.data) > 0:
            issue_id = response.data[0].get("id")
            logger.info(f"Issue logged successfully with ID: {issue_id}")
            return {
                "success": True,
                "issue_id": issue_id,
                "message": "Issue logged successfully. Please proceed to the next application."
            }
        else:
            # This case might occur if RLS prevents seeing the inserted row
            logger.warning(f"Issue logged for {application_id}, but no data returned in response (check RLS?).")
            return {
                "success": True, # Assume success if no exception, even if no data returned
                "issue_id": None,
                "message": "Issue logged, but no confirmation data returned. Please proceed to the next application."
            }

    except PostgrestAPIError as e:
        logger.error(f"Supabase API Error logging issue for {application_id}: {e}")
        logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Supabase API Error logging issue: {e.message}. Please proceed to the next application."
        }
    except Exception as e:
        logger.error(f"Unexpected Exception in log_application_issue for {application_id}: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Unexpected error logging issue: {str(e)}. Please proceed to the next application."
        }

@mcp.tool()
def log_simple_issue(
    company: str, 
    position: str,
    issue_type: str,
    issue_details: str
) -> Dict[str, Any]:
    """
    Simplified version that logs an issue without requiring user_id and application_id.
    Uses the default user ID and generates a random application ID.
    Ensures a basic application record exists before logging the issue.
    
    Args:
        company: Company name
        position: Position title
        issue_type: Type of issue (e.g., "Missing Information", "Decision Required") 
        issue_details: Detailed description of the issue
        
    Returns:
        Dictionary with issue ID and status
    """
    logger.info(f"log_simple_issue called for {position} at {company}")
    
    # Generate a random application ID
    application_id = str(uuid.uuid4())
    logger.info(f"Generated application_id: {application_id}")
    
    # Call the full function with the default user ID
    return log_application_issue(
        user_id=DEFAULT_USER_ID,
        application_id=application_id,
        company=company,
        position=position,
        issue_type=issue_type,
        issue_details=issue_details
    )

@mcp.tool()
def send_application_notification(
    user_id: str, 
    title: str, 
    message: str, 
    notification_type: str = "alert"
) -> Dict[str, Any]:
    """
    Send a notification to the user about an application issue or event
    
    Args:
        user_id: User's ID
        title: Notification title
        message: Notification message
        notification_type: Type of notification (default: "alert", must be one of: "application", "interview", "reminder", "alert")
        
    Returns:
        Dictionary with notification status
    """
    logger.info(f"send_application_notification called with: user_id={user_id}, title={title}, type={notification_type}")
    logger.info(f"Notification message: {message}")
    
    # Ensure the notification_type is valid according to schema constraints
    valid_types = ["application", "interview", "reminder", "alert"]
    if notification_type not in valid_types:
        logger.warning(f"Invalid notification_type '{notification_type}', defaulting to 'alert'")
        notification_type = "alert"
    
    try:
        logger.debug("Preparing to insert notification into notifications table")
        
        # Log the data being sent
        insert_data = {
            "user_id": user_id,
            "title": title,
            "content": message,
            "type": notification_type,
            "read": False,
            "created_at": datetime.now().isoformat()
        }
        logger.debug(f"Insert data: {insert_data}")
        
        # Insert notification into database
        logger.debug("Executing supabase insert for notifications")
        response = supabase.table("notifications").insert(insert_data).execute()
        logger.debug(f"Supabase notifications response: {response}")
        
        logger.info("Notification sent successfully")
        return {
            "success": True,
            "message": "Notification sent successfully. Please proceed to the next application."
        }
    except PostgrestAPIError as e:
        # Check specifically for the schema cache error
        if e.code == 'PGRST204':
             logger.error("Supabase schema cache error: Could not find the 'message' column.")
             logger.error("Please verify the 'notifications' table schema in Supabase and ensure the column exists and is named 'message'. Reloading the Supabase schema cache might be necessary.")
        else:
            logger.error(f"Supabase API Error sending notification: {e}")
            logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Supabase API Error sending notification: {e.message}. Please proceed to the next application."
        }
    except Exception as e:
        logger.error(f"Unexpected Exception in send_application_notification: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Unexpected error sending notification: {str(e)}. Please proceed to the next application."
        }

@mcp.tool()
def send_simple_notification(
    title: str, 
    message: str, 
    notification_type: str = "alert"
) -> Dict[str, Any]:
    """
    Simplified version that sends a notification without requiring user_id.
    Uses the default user ID.
    
    Args:
        title: Notification title
        message: Notification message
        notification_type: Type of notification (default: "alert", must be one of: "application", "interview", "reminder", "alert")
        
    Returns:
        Dictionary with notification status
    """
    logger.info(f"send_simple_notification called with title: {title}")
    
    # Call the full function with the default user ID
    return send_application_notification(
        user_id=DEFAULT_USER_ID,
        title=title,
        message=message,
        notification_type=notification_type
    )

logger.info("UserAssistance MCP tools defined, ready to run")

@mcp.tool()
def find_existing_answer(question_text: str, similarity_threshold: float = 0.8) -> Dict[str, Any]:
    """
    Searches for existing answers to semantically similar questions in the database.
    Generates a 384d embedding using sentence-transformers (gte-small) 
    and calls a Supabase RPC function to perform the native vector search.

    Args:
        question_text: The new question text to find answers for.
        similarity_threshold: Minimum cosine similarity score to consider a match.

    Returns:
        Dictionary containing 'found' (boolean) and 'answer_text' (string, if found).
    """
    logger.info(f"find_existing_answer called for question: {question_text}")

    if not DEFAULT_USER_ID:
        logger.error("Cannot find answer: Default User ID is not set.")
        return {"found": False, "answer_text": None, "message": "User ID not set"}

    if not supabase:
        logger.error("Cannot find answer: Supabase client is not initialized.")
        return {"found": False, "answer_text": None, "message": "Supabase client not available"}
        
    if not embedding_model_st:
        logger.error("Cannot find answer: Sentence Transformer model failed to load.")
        return {"found": False, "answer_text": None, "message": "Embedding model not available"}
        
    try:
        # 1. Generate 384d embedding using sentence-transformers (gte-small)
        logger.debug("Generating 384d embedding for question using thenlper/gte-small...")
        query_embedding = embedding_model_st.encode(question_text).tolist()
        # Check embedding dimension (optional)
        # logger.debug(f"Generated query embedding dimension: {len(query_embedding)}") 
        # logger.debug(f"Generated query embedding (first few dims): {query_embedding[:5]}...")

        # 2. Call Supabase RPC with the generated embedding
        # Assumes a Supabase function `match_user_answers_384` exists (created in migration):
        #   Takes (p_user_id UUID, query_embedding VECTOR(384), match_threshold FLOAT, match_count INT)
        #   Returns TABLE (id UUID, question_id UUID, answer_text TEXT, similarity FLOAT)
        rpc_function_name = "match_user_answers_384"
        logger.debug(f"Calling Supabase RPC '{rpc_function_name}' for user {DEFAULT_USER_ID}")
        response = supabase.rpc(
            rpc_function_name,
            {
                "p_user_id": DEFAULT_USER_ID,
                "query_embedding": query_embedding, # Pass the generated embedding
                "match_threshold": similarity_threshold,
                "match_count": 1, # Find the single best match above the threshold
            },
        ).execute()
        logger.debug(f"Supabase RPC response: {response}")

        if response.data and len(response.data) > 0:
            best_match = response.data[0]
            # Ensure the key 'answer_text' exists in the returned data
            if 'answer_text' in best_match:
                similarity = best_match.get('similarity', 'N/A')
                # Ensure similarity is a float or convertible to float for formatting
                try:
                    similarity_str = f"{float(similarity):.4f}"
                except (ValueError, TypeError):
                    similarity_str = str(similarity) # Fallback if conversion fails
                
                logger.info(f"Found similar answer with similarity {similarity_str}")
                return {
                    "found": True,
                    "answer_text": best_match["answer_text"],
                    "message": f"Found existing answer with similarity {similarity_str}"
                }
            else:
                 logger.warning("Found match via RPC, but 'answer_text' key missing in response data.")
                 return {"found": False, "answer_text": None, "message": "Match found but response format unexpected"}
        else:
            logger.info("No sufficiently similar answer found via RPC.")
            return {"found": False, "answer_text": None, "message": "No similar answer found"}

    except PostgrestAPIError as e:
        # Handle potential RPC errors (e.g., function not found)
        if f'relation "{rpc_function_name}" does not exist' in e.message or f'function {rpc_function_name}' in e.message:
             logger.error(f"Supabase RPC Error: '{rpc_function_name}' function not found. Please ensure the migration was applied.")
             return {"found": False, "answer_text": None, "message": f"Required database function '{rpc_function_name}' is missing."}
        logger.error(f"Supabase API Error searching for answer: {e}")
        logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
        logger.error(traceback.format_exc())
        return {"found": False, "answer_text": None, "message": f"Supabase API Error: {e.message}"}
    except Exception as e:
        logger.error(f"Unexpected Exception in find_existing_answer: {e}")
        logger.error(traceback.format_exc())
        # Handle potential model encoding errors
        if "embedding_model_st" in locals() and hasattr(e, "message") and "encode" in str(e):
             logger.error(f"Error during sentence-transformer encoding: {e}")
             return {"found": False, "answer_text": None, "message": f"Failed to generate text embedding: {e}"}
        return {"found": False, "answer_text": None, "message": f"Unexpected error: {str(e)}"}

@mcp.tool()
def ask_question(question_text: str) -> Dict[str, Any]:
    """
    Sends a question to the user and stores it for later retrieval of the answer.
    Uses the default authenticated user ID.

    Args:
        question_text: The question to ask the user.

    Returns:
        Dictionary with the status and the ID of the asked question.
    """
    logger.info(f"ask_question called with question: {question_text}")

    if not DEFAULT_USER_ID:
        logger.error("Cannot ask question: Default User ID is not set.")
        return {
            "success": False,
            "message": "Cannot ask question: Default User ID is not set.",
        }
        
    if not supabase:
         logger.error("Cannot ask question: Supabase client is not initialized.")
         return {
            "success": False,
            "message": "Cannot ask question: Supabase client not available.",
        }

    try:
        question_id = str(uuid.uuid4())
        logger.debug(f"Generated question_id: {question_id}")

        insert_data = {
            "id": question_id,
            "question_text": question_text,
        }
        logger.debug(f"Inserting question data into 'questions' table: {insert_data}")

        # Ensure the 'questions' table schema in Supabase matches:
        # Columns expected: id (uuid, pk), question_text (text), created_at (timestampz)
        response = supabase.table("questions").insert(insert_data).execute()
        logger.debug(f"Supabase insert response for questions: {response}")

        if response.data and len(response.data) > 0:
            logger.info(f"Question stored successfully with ID: {question_id}")
            # TODO: Implement actual sending of the question to the frontend/user
            # For now, we just log it and store it.
            return {
                "success": True,
                "question_id": question_id,
                "message": "Question logged successfully and is pending user answer.",
            }
        else:
            logger.warning(f"Question possibly stored (ID: {question_id}), but no data returned in response (check RLS?).")
            return {
                "success": True, # Assume success if no exception
                "question_id": question_id,
                "message": "Question logged, but no confirmation data returned. Pending user answer.",
            }

    except PostgrestAPIError as e:
        logger.error(f"Supabase API Error storing question: {e}")
        logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Supabase API Error storing question: {e.message}.",
        }
    except Exception as e:
        logger.error(f"Unexpected Exception in ask_question: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Unexpected error storing question: {str(e)}.",
        }

if __name__ == "__main__":
    logger.info("Starting UserAssistance MCP server")
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.critical(f"Fatal error in UserAssistance MCP server: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1) 