import os
from mcp.server.fastmcp import FastMCP
from supabase import create_client, PostgrestAPIError
from dotenv import load_dotenv
from typing import Dict, Any
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
        # Log to a file specific to this MCP
        logging.FileHandler("supabase_mcp_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
# Use a logger specific to this MCP
logger = logging.getLogger("supabase_mcp")

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
    # from unittest.mock import MagicMock
    # supabase = MagicMock()
    logger.warning("Using mock Supabase client due to initialization error")


# Optional: Default credentials for testing (Replicated from user_assistance_mcp)
DEFAULT_EMAIL = os.getenv("DEFAULT_EMAIL", "test@gmail.com")
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "password")

# Global variable to store current user session (Original from supabase_mcp)
# current_user_session = None # Commenting out, using DEFAULT_USER_ID logic instead

# Initialize Sentence Transformer model (Moved from user_assistance_mcp)
# Using gte-small as requested, which produces 384 dimensions
# This might take a moment on first run as the model downloads
embedding_model_st = None # Initialize as None
try:
    logger.info("Loading sentence-transformer model: thenlper/gte-small")
    embedding_model_st = SentenceTransformer('thenlper/gte-small')
    logger.info("Sentence-transformer model loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load sentence-transformer model: {e}")
    # embedding_model_st remains None if loading fails

# Default user ID logic (Moved from user_assistance_mcp)
DEFAULT_USER_ID = None
try:
    # Use default credentials
    user_email = DEFAULT_EMAIL
    user_password = DEFAULT_PASSWORD
    
    # Authenticate with Supabase
    auth_response = supabase.auth.sign_in_with_password({
        "email": user_email,
        "password": user_password
    })
    
    # Store the user ID
    DEFAULT_USER_ID = auth_response.user.id
    logger.info(f"Successfully authenticated as {auth_response.user.email}, user ID: {DEFAULT_USER_ID}")
    
    # Store the session for potential future use (though current functions rely on DEFAULT_USER_ID)
    current_user_session = auth_response.session
    
except Exception as e:
    logger.error(f"Automatic authentication failed: {str(e)}")
    logger.error(traceback.format_exc())
    # Fall back to a static ID if we can't get one from auth
    DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000000"
    logger.warning(f"Using fallback user ID: {DEFAULT_USER_ID}")
    # The MCP will continue to run, but functions requiring authentication might have issues


mcp = FastMCP("supabase") # Use the existing supabase MCP instance
logger.info("FastMCP initialized for supabase")

@mcp.tool()
def insert_application(position_title: str, company_name: str, link: str) -> Dict[str, Any]:
    """
    Insert a new application record into the applications table.
    
    Args:
        position_title: The title of the position applied for
        company_name: The name of the company applied to
        link: The link to the job application or company page
        
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
        # user_id = current_user_session.user.id # Using DEFAULT_USER_ID instead for consistency
        if not DEFAULT_USER_ID:
             logger.error("Cannot insert application: Default User ID is not set.")
             return {"success": False, "message": "Default User ID not available"}

        # Insert the application into the database
        response = supabase.table("applications").insert({
            "user_id": DEFAULT_USER_ID, # Use DEFAULT_USER_ID
            "position_title": position_title,
            "company_name": company_name,
            "link": link,
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

# --- Functions moved from user_assistance_mcp --- 

@mcp.tool() # Use the supabase mcp instance
def find_existing_answer(question_text: str) -> Dict[str, Any]:
    """
    Searches for existing answers to semantically similar questions in the database.
    Generates a 384d embedding using sentence-transformers (gte-small) 
    and calls a Supabase RPC function to perform the native vector search.
    Returns a string of the question/issue and the corresponding answer from the user.

    Args:
        question_text: The new question text to find answers for.

    Returns:
        Dictionary containing 'found' (boolean) and 'question_answer_text' (string, if found).
    """
    logger.info(f"find_existing_answer called for question: {question_text}")

    MATCH_TYPES = ["missing_information"]
    SIMILARITY_THRESHOLD = 0.6

    if not DEFAULT_USER_ID:
        logger.error("Cannot find answer: Default User ID is not set.")
        return {"found": False, "question_answer_text": None, "message": "User ID not set"}
        
    if not embedding_model_st:
        logger.error("Cannot find answer: Sentence Transformer model failed to load.")
        return {"found": False, "question_answer_text": None, "message": "Embedding model not available"}
        
    try:
        # 1. Generate 384d embedding using sentence-transformers (gte-small)
        logger.debug("Generating 384d embedding for question using thenlper/gte-small...")
        query_embedding = embedding_model_st.encode(question_text).tolist()

        # 2. Call Supabase RPC with the generated embedding
        rpc_function_name = "match_application_issues_384"
        logger.debug(f"Calling Supabase RPC '{rpc_function_name}' for user {DEFAULT_USER_ID}")
        response = supabase.rpc(
            rpc_function_name,
            {
                "p_user_id": DEFAULT_USER_ID,
                "query_embedding": query_embedding,
                "match_threshold": SIMILARITY_THRESHOLD,
                "match_count": 3, 
                "match_types": MATCH_TYPES
            },
        ).execute()
        logger.debug(f"Supabase RPC response: {response}")

        if response.data and len(response.data) > 0:
            best_match = response.data[0]
            if 'issue_details' in best_match and 'resolution_note' in best_match:
                similarity = best_match.get('similarity', 'N/A')
                try:
                    similarity_str = f"{float(similarity):.4f}"
                except (ValueError, TypeError):
                    similarity_str = str(similarity)
                
                logger.info(f"Found similar answer with similarity {similarity_str}")
                return {
                    "found": True,
                    "question_answer_text": "Question: " + best_match["issue_details"] + " " + "Answer: " + best_match["resolution_note"],
                    "message": f"Found existing answer with similarity {similarity_str}"
                }
            else:
                 logger.warning("Found match via RPC, but either 'issue_details' or 'resolution_note' key missing in response data.")
                 return {"found": False, "answquestion_answer_texter_text": None, "message": "Match found but response format unexpected"}
        else:
            logger.info("No sufficiently similar answer found via RPC.")
            return {"found": False, "question_answer_text": None, "message": "No similar answer found"}

    except PostgrestAPIError as e:
        if f'relation "{rpc_function_name}" does not exist' in e.message or f'function {rpc_function_name}' in e.message:
             logger.error(f"Supabase RPC Error: '{rpc_function_name}' function not found. Please ensure the migration was applied.")
             return {"found": False, "question_answer_text": None, "message": f"Required database function '{rpc_function_name}' is missing."}
        logger.error(f"Supabase API Error searching for answer: {e}")
        logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
        logger.error(traceback.format_exc())
        return {"found": False, "question_answer_text": None, "message": f"Supabase API Error: {e.message}"}
    except Exception as e:
        logger.error(f"Unexpected Exception in find_existing_answer: {e}")
        logger.error(traceback.format_exc())
        if "embedding_model_st" in locals() and hasattr(e, "message") and "encode" in str(e):
             logger.error(f"Error during sentence-transformer encoding: {e}")
             return {"found": False, "question_answer_text": None, "message": f"Failed to generate text embedding: {e}"}
        return {"found": False, "question_answer_text": None, "message": f"Unexpected error: {str(e)}"}

# @mcp.tool() # Use the supabase mcp instance
# def ask_question(question_text: str) -> Dict[str, Any]:
#     """
#     Sends a question to the user and stores it for later retrieval of the answer.
#     Uses the default authenticated user ID.

#     Args:
#         question_text: The question to ask the user.

#     Returns:
#         Dictionary with the status and the ID of the asked question.
#     """
#     logger.info(f"ask_question called with question: {question_text}")

#     if not DEFAULT_USER_ID:
#         logger.error("Cannot ask question: Default User ID is not set.")
#         return {
#             "success": False,
#             "message": "Cannot ask question: Default User ID is not set.",
#         }
        
#     if not supabase or isinstance(supabase, MagicMock):
#          logger.error("Cannot ask question: Supabase client is not initialized or is a mock.")
#          return {
#             "success": False,
#             "message": "Cannot ask question: Supabase client not available.",
#         }

#     try:
#         question_id = str(uuid.uuid4())
#         logger.debug(f"Generated question_id: {question_id}")

#         insert_data = {
#             "id": question_id,
#             "question_text": question_text,
#             # Assuming 'user_id' column exists in 'questions' table and should be populated
#             "user_id": DEFAULT_USER_ID,
#         }
#         logger.debug(f"Inserting question data into 'questions' table: {insert_data}")

#         # Ensure the 'questions' table schema in Supabase matches:
#         # Columns expected: id (uuid, pk), question_text (text), user_id (uuid, fk), created_at (timestampz)
#         response = supabase.table("questions").insert(insert_data).execute()
#         logger.debug(f"Supabase insert response for questions: {response}")

#         if response.data and len(response.data) > 0:
#             logger.info(f"Question stored successfully with ID: {question_id}")
#             # TODO: Implement actual sending of the question to the frontend/user
#             # For now, we just log it and store it.
#             return {
#                 "success": True,
#                 "question_id": question_id,
#                 "message": "Question logged successfully and is pending user answer.",
#             }
#         else:
#             logger.warning(f"Question possibly stored (ID: {question_id}), but no data returned in response (check RLS?).")
#             return {
#                 "success": True, # Assume success if no exception
#                 "question_id": question_id,
#                 "message": "Question logged, but no confirmation data returned. Pending user answer.",
#             }

#     except PostgrestAPIError as e:
#         logger.error(f"Supabase API Error storing question: {e}")
#         logger.error(f"Details: {e.details}, Code: {e.code}, Hint: {e.hint}, Message: {e.message}")
#         logger.error(traceback.format_exc())
#         return {
#             "success": False,
#             "message": f"Supabase API Error storing question: {e.message}.",
#         }
#     except Exception as e:
#         logger.error(f"Unexpected Exception in ask_question: {e}")
#         logger.error(traceback.format_exc())
#         return {
#             "success": False,
#             "message": f"Unexpected error storing question: {str(e)}.",
#         }

# --- End moved functions --- 

if __name__ == "__main__":
    logger.info("Starting Supabase MCP server") # Update log message
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.critical(f"Fatal error in Supabase MCP server: {e}") # Update log message
        logger.critical(traceback.format_exc())
        sys.exit(1) 
