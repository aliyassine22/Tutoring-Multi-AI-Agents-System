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

SCOPES = ["https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/calendar"]
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


def _get_google_creds(scopes: List[str]) -> Optional[Credentials]:
  """Helper function to get Google API credentials."""
  creds = None
  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  print('path: ',HERE)
  if os.path.exists(Path(f"{HERE}/tokener.json")):
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
    return creds

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
    name="send_email",
    description="""
        Send an email from the user's Gmail account.
        Requires the recipient's email address (`to`), the email content (`body`),
        and an optional `subject`. This tool only creates a draft; it does not send the email.
    """
)
def gmail_send_message(to: str, body: str, subject: str ="Tutoring Session"):
  """Create and send an email message
  Print the returned  message id
  Returns: Message object, including message id

  Load pre-authorized user credentials from the environment.
  TODO(developer) - See https://developers.google.com/identity
  for guides on implementing OAuth2 for the application.
  """

  creds = _get_google_creds(SCOPES)
  try:
    # create gmail api client
    service = build("gmail", "v1", credentials=creds)

    message = EmailMessage()
    
    # time_str = meeting_date.strftime("%H:%M")

    content=f"""
    Greetings,
    
    I hope this email finds you well,
    
    Note that we will have our meeting as scheduled , to access the meeting session, please use the following: https://www.youtube.com/ ,
    
    For our session, we will cover the following topics:
    
    {body}
    
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
    send_message = (
        service.users()
        .messages()
        .send(userId="me", body=create_message)
        .execute()
    )
    print(f'Message Id: {send_message["id"]}')
  except HttpError as error:
    print(f"An error occurred: {error}")
    send_message = None

@mcp.tool(
    name='scrape_calendar',
    description=(
        "Lists up to 10 upcoming events from the user's primary Google Calendar. "
        "Returns a list of events, each containing its summary (title), start time, and event ID."
    )

)
def scrape_calendar():
  """Shows basic usage of the Google Calendar API.
     Prints the start and name of the next 10 events on the user's calendar.
  """
  creds = _get_google_creds(SCOPES)
  try:
    service = build("calendar", "v3", credentials=creds)

    # Call the Calendar API
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    print("Getting the upcoming 10 events")
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
            q="Available Tutoring Session",  # Use the 'q' parameter for free-text search
        )
        .execute()
    )
    events = events_result.get("items", [])

    if not events:
      print("No upcoming events found.")
      return

    # Prints the start and name of the next 10 events
    for event in events:
    #   print(event)
    #   start = event["start"].get("dateTime", event["start"].get("date"))
    #   print(start, event["summary"])
    #   print('eventId:',event["id"])
        event_list = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            event_list.append({
                "summary": event.get("summary", "No Title"),
                "start": start,
                "id": event["id"]
            })
        return event_list
  except HttpError as error:
    print(f"An error occurred: {error}")

@mcp.tool(
    name='update_calendar',
    description=(
    """
    Updates an existing event in the user's primary Google Calendar.
    Requires the `eventId`. Optional fields include `summary`, `description`,
    `start_time`, `end_time` (in ISO format), and a list of `attendees` emails.
    """
    )
)
def update_calendar(
    eventId: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    attendees: Optional[List[str]]= None
):
  """
  Updates an existing event in the primary Google Calendar.
  Fetches the event, modifies specified fields, and pushes the update.
  """
  creds = _get_google_creds(SCOPES)
  if not creds:
      return {"status": "error", "message": "Authentication failed."}
      
  try:
    service = build("calendar", "v3", credentials=creds)

    # First, get the existing event to serve as a base
    event = service.events().get(calendarId='primary', eventId=eventId).execute()

    # Update fields only if new values were provided by the agent
    if summary is not None:
        event['summary'] = summary
    if description is not None:
        event['description'] = description
    if start_time is not None:
        event['start']['dateTime'] = start_time
        # Assume end time should also be updated if start time is, or handle as needed
        if end_time is None: # If no end time provided, default to one hour after start
            from dateutil import parser
            from datetime import timedelta
            end_time_dt = parser.isoparse(start_time) + timedelta(hours=1)
            event['end']['dateTime'] = end_time_dt.isoformat()
    if end_time is not None:
        event['end']['dateTime'] = end_time
    if attendees is not None:
        event['attendees'] = [{'email': email} for email in attendees]
    
    updated_event = service.events().update(
        calendarId='primary',
        eventId=event['id'],
        body=event,
        sendUpdates='all' # Notifies attendees of the change
    ).execute()

  except HttpError as error:
    print(f"An error occurred: {error}")

@mcp.tool(
    name="cancel_event",
    description="Cancels or deletes an event from the user's primary Google Calendar. Requires the `eventId` of the event to be cancelled."
)
def delete_from_calendar(eventId):
  """
    Deletes an event from the primary Google Calendar using its eventId.
  """
  creds = _get_google_creds(SCOPES)
  try:
    service = build("calendar", "v3", credentials=creds)
    event= service.events().delete(calendarId='primary',eventId=eventId ).execute()

  except HttpError as error:
        print(f"An error occurred: {error}")

# I used the following tool to populate my calendar
@mcp.tool(
    name="create_calendar_event",
    description=(
        "Creates a new event in the user's primary Google Calendar. "
        "Requires a `summary` (the event title), a `start_time`, and an `end_time`. "
        "Times must be in ISO format (e.g., '2025-08-22T19:00:00'). "
        "Optionally accepts a `description` for the event details."
    )
)
def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: Optional[str] = None
):  
  """
  Shows basic usage of the Google Calendar API.
  Prints the start and name of the next 10 events on the user's calendar.
  """
  creds = _get_google_creds(SCOPES)
  try:
    service = build("calendar", "v3", credentials=creds)
    GMT_OFF = '03:00'
    event_body = {
        'summary': "Available Tutoring Session",
        'description': description,
        'start': {'dateTime': start_time, 'timeZone': 'UTC'},
        'end':   {'dateTime': end_time, 'timeZone': 'UTC'},
        # 'attendees': [], # Add attendees here if needed
    }

    event = service.events().insert(calendarId='primary', body=event_body).execute()

    print('''*** %r event added:
    Start: %s
    End:   %s''' % (event['summary'].encode('utf-8'),
                    event['start']['dateTime'], event['end']['dateTime']))

  except HttpError as error:
        print(f"An error occurred: {error}")

if __name__ == "__main__":
    mcp.run(transport="sse")
    
    
