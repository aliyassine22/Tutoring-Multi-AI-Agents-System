# this ref was my guide setting up the basis for this project: https://github.com/PraveenKS30/google-adk/blob/main/02_basic_agent_no_web/agent.py
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
import asyncio
from dotenv import load_dotenv
from agent.agent import get_agent
from typing import Dict, Tuple, Optional
from fastapi import FastAPI, HTTPException, status, Query
from pydantic import BaseModel
import os, json, base64
from typing import AsyncGenerator, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from fastapi import FastAPI, UploadFile, File
from typing import Annotated

load_dotenv()
APP_NAME = "tutoring_agent"
USER_ID = "user_12345"
SESSION_ID = "session_12345"

app = FastAPI()
# CORS so Streamlit (another port) can call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SendRequest(BaseModel):
    query: str
    # Optional: allow overriding IDs per request (defaults to globals)
    user_id: Optional[str] = None
    session_id: Optional[str] = None

session_service: InMemorySessionService | None = None
runner: Runner | None = None
answers: Dict[Tuple[str, str], Dict[str, str]] = {}


@app.on_event("startup")
async def _startup():
    """Build session + runner once and reuse."""
    global session_service, runner
    # create memory session 
    session_service = InMemorySessionService()
    await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    # get the agent 
    root_agent = await get_agent()
    # create runner instance
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)


async def _run_query_and_store(query: str, user_id: str, session_id: str):
    """Consume runner.run_async events; save the final answer in the in-memory store."""
    if runner is None:
        answers[(user_id, session_id)] = {"status": "error", "error_msg": "Runner not initialized"}
        return

    content = types.Content(role="user", parts=[types.Part(text=query)])
    events = runner.run_async(
        new_message=content,
        user_id=user_id,
        session_id=session_id,
    )

    try:
        async for event in events:
            if event.is_final_response():
                final_text = event.content.parts[0].text
                answers[(user_id, session_id)] = {"status": "done", "answer": final_text}
                return
        # If we exit the loop without a final response:
        answers[(user_id, session_id)] = {"status": "error", "error_msg": "No final response received."}
    except Exception as e:
        answers[(user_id, session_id)] = {"status": "error", "error_msg": str(e)}

# @app.post("/upload-pdf/")
# async def upload_pdf(file: UploadFile):
#     if file.content_type != "application/pdf":
#         return {"message": "Only PDF files are allowed."}

#     try:
#         # Read the file content asynchronously
#         contents = await file.read()
#         # rag file upload

#         return {"filename": file.filename, "message": "PDF uploaded successfully!"}
#     except Exception as e:
#         return {"message": f"There was an error uploading the file: {e}"}


@app.post("/send")
async def send(req: SendRequest):
    """
    Start the agent run in the background and return immediately.
    Poll /answer to retrieve the result.
    """
    user_id = req.user_id or USER_ID
    session_id = req.session_id or SESSION_ID

    # (Re)create the session if needed (idempotent for in-memory demo)
    if session_service is None:
        # Fix here - don't return a tuple, return an HTTPException
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Server not fully initialized yet"
        )
    
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)

    # Mark as pending and launch background task
    answers[(user_id, session_id)] = {"status": "pending"}
    asyncio.create_task(_run_query_and_store(req.query, user_id, session_id))

    return {"ok": True, "user_id": user_id, "session_id": session_id, "status": "pending"}

@app.get("/answer")
async def answer(
    user_id: str = Query(default=USER_ID),
    session_id: str = Query(default=SESSION_ID),
):
    """
    Retrieve the final answer (polling).
    """
    try:
        key = (user_id, session_id)
        state = answers.get(key)

        if state is None:
            # Nothing was launched for this (user_id, session_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, 
                                detail="No pending or completed run for this session.")

        # Return state information regardless of status
        return state
        
    except Exception as e:
        # Catch any unexpected errors and return a meaningful message
        return {"status": "error", "error_msg": f"Unexpected error: {str(e)}"}

#  simplest endpoint directly return the ourput
@app.post("/test")
async def test_agent(query: str = Body(..., embed=True)):
    """Direct synchronous test endpoint"""
    if runner is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
                            detail="Server not fully initialized yet")

    content = types.Content(role="user", parts=[types.Part(text=query)])
    response = ""
    
    events = runner.run_async(
        new_message=content,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    
    async for event in events:
        if event.is_final_response():
            response = event.content.parts[0].text
            break
    
    return {"response": response}








# # this was build based on https://google.github.io/adk-docs/streaming/custom-streaming/#enabling-session-resumption, did not work for some reason
# # got this error:
# #   PydanticSerializationUnexpectedValue(Expected `enum` - serialized value may not be as expected [input_value='TEXT', input_type=str])
# #   return self.__pydantic_serializer__.to_python(
# # Based on what they suggest, i should use this model: gemini-2.0-flash-live-001


# from google.adk.agents import LlmAgent
# from google.adk.sessions import InMemorySessionService
# from google.adk.runners import InMemoryRunner, Runner, LiveRequestQueue, RunConfig
# from google.genai import types
# import asyncio
# from dotenv import load_dotenv
# from agent.agent import get_agent
# from typing import Dict, Tuple, Optional
# from fastapi import FastAPI, HTTPException, status, Query
# from pydantic import BaseModel
# import os, json, base64
# from typing import AsyncGenerator, Dict, Any
# from fastapi import FastAPI, HTTPException, Body
# from fastapi.middleware.cors import CORSMiddleware
# from sse_starlette.sse import EventSourceResponse
# from fastapi import FastAPI, UploadFile, File
# from typing import Annotated
# from google.genai.types import Part, Content, Blob, Modality
# from fastapi.responses import StreamingResponse
# from fastapi import Request

# load_dotenv()
# app_name = "tutoring_agent"
# user_id = 12345
# session_id = 2345

# app = FastAPI()
# # CORS so Streamlit (another port) can call the API
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# class SendRequest(BaseModel):
#     query: str
#     # Optional: allow overriding IDs per request (defaults to globals)
#     user_id: Optional[int] = None
#     session_id: Optional[int] = None

# session_service: InMemorySessionService | None = None
# root_agent: LlmAgent | None = None
# active_sessions: Dict[str, LiveRequestQueue] = {}  # Fixed type annotation

# @app.on_event("startup")
# async def startup():
#     """Initialize the session service and agent once at startup."""
#     global session_service, root_agent
#     session_service = InMemorySessionService()
#     root_agent = await get_agent()

# async def start_agent_session(user_id_str: str):
#     """Create a session for a specific user and return streaming events."""
#     global session_service, root_agent
    
#     if session_service is None or root_agent is None:
#         raise HTTPException(status_code=503, detail="Server not fully initialized yet")
        
#     # Create a session for this user
#     session = await session_service.create_session(
#         app_name=app_name,
#         user_id=user_id_str,  
#         session_id=f"session_{user_id_str}"
#     )
#     run_config = RunConfig(response_modalities=[Modality.TEXT])  # Use proper enum
    
#     # Create a runner for this user
#     runner = InMemoryRunner(app_name=app_name, agent=root_agent)
    
#     # Create a LiveRequestQueue for this session
#     live_request_queue = LiveRequestQueue()

#     # Start agent session
#     live_events = runner.run_live(
#         session=session,
#         live_request_queue=live_request_queue,
#         run_config=run_config,
#     )
    
#     return live_events, live_request_queue

# async def agent_to_client_sse(live_events):
#     """Agent to client communication via SSE"""
#     async for event in live_events:
#         # If the turn complete or interrupted, send it
#         if event.turn_complete or event.interrupted:
#             message = {
#                 "turn_complete": event.turn_complete,
#                 "interrupted": event.interrupted,
#             }
#             yield f"data: {json.dumps(message)}\n\n"
#             print(f"[AGENT TO CLIENT]: {message}")
#             continue

#         # Read the Content and its first Part
#         part: Part = (
#             event.content and event.content.parts and event.content.parts[0]
#         )
#         if not part:
#             continue

#         # If it's text, send it (whether partial or final)
#         if part.text:
#             message = {
#                 "mime_type": "text/plain",
#                 "data": part.text
#             }
#             yield f"data: {json.dumps(message)}\n\n"
#             print(f"[AGENT TO CLIENT]: text/plain: {part.text}")

# @app.get("/events/{user_id}")
# async def sse_endpoint(user_id: int):
#     """SSE endpoint for agent to client communication"""

#     # Convert to string for consistency
#     user_id_str = str(user_id)
    
#     # Check if there's already an active session
#     if user_id_str in active_sessions:
#         # Clean up existing session to avoid conflicts
#         active_sessions[user_id_str].close()
    
#     # Start a new agent session
#     live_events, live_request_queue = await start_agent_session(user_id_str)

#     # Store the request queue for this user
#     active_sessions[user_id_str] = live_request_queue

#     def cleanup():
#         live_request_queue.close()
#         if user_id_str in active_sessions:
#             del active_sessions[user_id_str]
#         print(f"Client #{user_id} disconnected from SSE")

#     async def event_generator():
#         try:
#             async for data in agent_to_client_sse(live_events):
#                 yield data
#         except Exception as e:
#             print(f"Error in SSE stream: {e}")
#         finally:
#             cleanup()

#     return StreamingResponse(
#         event_generator(),
#         media_type="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "Connection": "keep-alive",
#             "Access-Control-Allow-Origin": "*",
#             "Access-Control-Allow-Headers": "Cache-Control"
#         }
#     )

# @app.post("/send/{user_id}")
# async def send_message_endpoint(user_id: int, request: Request):
#     """HTTP endpoint for client to agent communication"""

#     user_id_str = str(user_id)

#     # Get the live request queue for this user
#     live_request_queue = active_sessions.get(user_id_str)
#     if not live_request_queue:
#         # If no session exists, create one
#         try:
#             live_events, live_request_queue = await start_agent_session(user_id_str)
#             active_sessions[user_id_str] = live_request_queue
#         except Exception as e:
#             return {"error": f"Failed to create session: {str(e)}"}

#     # Parse the message
#     message = await request.json()
#     mime_type = message["mime_type"]
#     data = message["data"]

#     # Send the message to the agent
#     if mime_type == "text/plain":
#         content = Content(role="user", parts=[Part.from_text(text=data)])
#         live_request_queue.send_content(content=content)
#         print(f"[CLIENT TO AGENT]: {data}")
#     else:
#         return {"error": f"Mime type not supported: {mime_type}"}

#     return {"status": "sent"}

# @app.post("/test")
# async def test_agent(query: str = Body(..., embed=True)):
#     """Direct synchronous test endpoint"""
#     global session_service, root_agent
    
#     if session_service is None or root_agent is None:
#         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
#                             detail="Server not fully initialized yet")
    
#     # Create a temporary runner for this test
#     test_runner = InMemoryRunner(app_name=app_name, agent=root_agent)
    
#     content = types.Content(role="user", parts=[types.Part(text=query)])
#     response = ""
    
#     events = test_runner.run_async(
#         new_message=content,
#         user_id=user_id,
#         session_id=session_id,
#     )
    
#     async for event in events:
#         if event.is_final_response():
#             response = event.content.parts[0].text
#             break
    
#     return {"response": response}

# # @app.post("/upload-pdf/")
# # async def upload_pdf(file: UploadFile):
# #     if file.content_type != "application/pdf":
# #         return {"message": "Only PDF files are allowed."}

# #     try:
# #         # Read the file content asynchronously
# #         contents = await file.read()
# #         # rag file upload

# #         return {"filename": file.filename, "message": "PDF uploaded successfully!"}
# #     except Exception as e:
# #         return {"message": f"There was an error uploading the file: {e}"}
