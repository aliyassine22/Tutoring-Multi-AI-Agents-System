import os, sys
import openai

# adk tools imports
import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
# from __future__ import annotations
import base64
import mimetypes
import os
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
HERE = Path(__file__).resolve().parent      


# we need to enable the setup at this level
sys.path.append('../..')
from dotenv import load_dotenv, find_dotenv
_=load_dotenv(find_dotenv()) # read local .env file
from mcp.server.fastmcp import FastMCP
from typing import Literal, Dict, Any, List, Optional
from RAG_SETUP import rag_tool
from pydantic import ValidationError


openai.api_key =os.environ['OPENAI_API_KEY']
mcp = FastMCP(
    name="langGraph_Demo",
    host="0.0.0.0",
    port="8787")

@mcp.tool(
    name="probe_topic",
    description=(
        "Educated probe over course corpora. "
        "Intents: presence (syllabus), resources (syllabus), material (chapters), "
        "exercises (assignments), tests (exams)."
    ),
)
def mcp_probe_topic(
    topic: str,
    intent: Literal["presence", "material", "exercises", "tests", "resources"] = "presence",
    lectures: Optional[List[int]] = None,
    k: int = 15,
) -> Dict[str, Any]:
    """
    MCP wrapper that validates inputs with Pydantic, then delegates to _probe_topic_fn.
    Returns a JSON-serializable dict.
    """
    data = {"topic": topic, "intent": intent, "lectures": lectures, "k": k}
    try:
        args = rag_tool.ProbeArgs(**data)  # raises ValidationError if bad
    except ValidationError as e:
        # Return a structured error payload (still JSON-serializable)
        return {"error": "validation_error", "details": e.errors()}

    # Call your underlying function with validated args.
    # exclude_none avoids sending spurious None values.
    return rag_tool._probe_topic_fn(**args.model_dump(exclude_none=True))

@mcp.tool(
    name="draf_email",
    description="""
    create an email draft that is to be send to a specified email
    """
)
def gmail_create_draft(to: str, body: str, subject: str ="Tutoring Session"):
  """Create and insert a draft email.
   Print the returned draft's message and id.
   Returns: Draft object, including draft id and message meta data.

  Load pre-authorized user credentials from the environment.
  TODO(developer) - See https://developers.google.com/identity
  for guides on implementing OAuth2 for the application.
  
Args:
    to (str): Recipient email address (RFC 5322 format).
    body (str): Plain-text email content (e.g., the planned session outline).
    meeting_date (datetime.datetime): The meeting’s date/time. If timezone-aware,
        it will be formatted accordingly; if naive, treat as UTC unless your
        implementation defines otherwise.

Returns:
    dict: Gmail `Draft` resource as returned by the API, e.g.
        `{"id": "<draft_id>", "message": {...}}`.

Raises:
    ValueError: If inputs are missing or invalid (e.g., empty `to` or `body`).
    googleapiclient.errors.HttpError: If the Gmail API request fails.

Notes:
    - This function only creates a draft; sending the email is a separate action.
    - Subject line and body formatting are implementation-defined.
  """
  creds = None
  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  print('path: ',HERE)
  if os.path.exists(Path(f"{HERE}/tokern.json")):
      creds = Credentials.from_authorized_user_file(f"{HERE}/token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
      if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
      else:
        flow = InstalledAppFlow.from_client_secrets_file(f"{HERE}/credentials.json", SCOPES)
        creds = flow.run_local_server(host="localhost", port=50759)  # http://localhost:50759/

  with open(f"{HERE}/token.json", "w", encoding="utf-8") as f:
    f.write(creds.to_json())
  try:
    # create gmail api client
    service = build("gmail", "v1", credentials=creds)

    message = EmailMessage()
    
    # time_str = meeting_date.strftime("%H:%M")

    content="""
    Greetings,
    
    I hope this email finds you well,
    
    Note that we will have our meeting on _____ , to access the meeting session, please use the following https://www.youtube.com/ ,
    
    For our session, we will cover the following topics:
      
    """+ body + """
    
    Best regards,
    Ali
    """
    
    message.set_content(content)

    message["To"] = to
    message["From"] = "ey8151860@gmail.com"
    message["Subject"] = subject

    # encoded message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    create_message = {"message": {"raw": encoded_message}}
    # pylint: disable=E1101
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body=create_message)
        .execute()
    )

    print(f'Draft id: {draft["id"]}\nDraft message: {draft["message"]}')

  except HttpError as error:
    print(f"An error occurred: {error}")
    draft = None

if __name__ == "__main__":
    mcp.run(transport="sse")