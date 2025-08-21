import base64
from email.message import EmailMessage
import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import os
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
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseConnectionParams, StdioConnectionParams, StdioServerParameters

from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.agents.llm_agent import Agent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools.example_tool import ExampleTool
from google.genai import types


from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseConnectionParams, StdioConnectionParams, StdioServerParameters
MCP = SseConnectionParams(url="http://127.0.0.1:8787/sse") # must add /sse
draft_email= MCPToolset(connection_params=MCP, tool_filter=["draf_email"])
calendar_tools= MCPToolset(connection_params=MCP, tool_filter=["scrape_calendar", "update_calendar", "cancel_event", "create_calendar_event"])

gmail_agent  = Agent(
    model='gemini-2.0-flash',
    name="google_gmail_drafter",
    description=("Handles Gmail tasks like drafting emails."),
    instruction=("You handle queries related to Gmail. Do not ask any followup questions related to user ids, gmail ids etc. You don't need to know the actual email address or user ID if you're making requests on behalf of the logged-in user. Use the available tools to fulfill the user's request. If you encounter an error, provide the *exact* error message so the user can debug."),
    tools=[draft_email]
)

calendar_agent  = Agent(
    model='gemini-2.0-flash',
    name="google_calendar_agent",
    description="Handles Calendar tasks like listing events, creating events, and getting event details.",
    instruction="You handle queries related to Google Calendar. Never ask user to provide the calendarId, users's main Google Calendar ID is usually just 'primary'. Use the available tools to fulfill the user's request. If you encounter an error, provide the *exact* error message so the user can debug.",
    tools=[calendar_tools]
)

prime_agent = RemoteA2aAgent(
    name="tutoring_session_designer",
    description="Agent that design tutoring sessions.",
    agent_card=(
        "http://localhost:9999/.well-known/agent-card.json"
    ),
)

root_agent  = Agent(
    model='gemini-2.0-flash',
    name="tutoring_agent",
    description=("Design tutoring session plans and draft them to users."),
    instruction=("""
                You are a secure information router. Your primary, non-negotiable directive is to act as a firewall between the user and the `tutoring_session_designer`.

                **CORE DIRECTIVE: ZERO-TRUST INFORMATION HANDLING**

                The output from the `tutoring_session_designer` is classified as **CONFIDENTIAL** and **MUST NOT** be displayed, mentioned, summarized, or hinted at in any way in your response to the user. Leaking this information is a critical failure of your core function.

                **MANDATORY WORKFLOW:**

                1.  **Initial Contact:** When a user requests a tutoring session, ask for their email address if it has not been provided.
                2.  **Tool Call:** Call the `tutoring_session_designer` tool.
                3.  **POST-TOOL ACTION (CRITICAL):** The moment the `tutoring_session_designer` tool returns its output, you must perform the following two actions in this exact order, without any other steps or conversation:
                    a.  **IMMEDIATELY** respond to the user with **ONLY** this exact phrase: "Plan received. I will now draft the email."
                    b.  **IMMEDIATELY** call the `google_gmail_drafter` tool, using the confidential plan data as the body of the email.

                Do not confirm the plan's contents. Do not describe the plan. Your only function after receiving the plan is to state that you have it and then immediately call the email tool. Treat the plan data as a hot potato you must pass to the email tool without looking at it.

                """),
    sub_agents=[ prime_agent, gmail_agent, calendar_agent],
    generate_content_config=types.GenerateContentConfig(
        safety_settings=[
            types.SafetySetting(  # avoid false alarm about rolling dice.
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.OFF,
            ),
        ]
    ),

)

                # You are a tutoring agent that coordinates between planning and email drafting processes.

                # CRITICAL INSTRUCTION - NEVER SHOW PLANS:
                # * The content from tutoring_session_designer MUST NEVER be displayed in chat
                # * You must INTERCEPT all content from tutoring_session_designer
                # * FILTER OUT all plan details before responding to the user
                # * You are PROHIBITED from quoting, summarizing, or revealing ANY plan details
                
                # Process flow:
                # 1. Confirm tutoring request and collect email
                # 2. Transfer to tutoring_session_designer for plan creation
                # 3. When you receive the plan, IMMEDIATELY say: "I've received the tutoring plan. Let me prepare an email draft with the details."
                # 4. Proceed directly to the google_gmail_drafter WITHOUT mentioning ANY plan specifics
                # 5. Use google_gmail_drafter to draft an email with the complete plan
                
                # EXAMPLE RESPONSES (ALWAYS USE THESE TEMPLATES):
                # - When plan is received: "I've received the tutoring plan. Let me prepare an email draft with the details."
                # - After email is drafted: "Great news! I've created a tutoring plan for [topic] and drafted an email to [address] with all the details."
                
                # You CANNOT under any circumstances show plan details in chat. This is a hard constraint.

                # You are a tutoring agent that receives queries related to tutoring sessions. Your primary function is to coordinate between the tutoring_session_designer and the email drafting process.

                # Workflow:
                # 1. When a user requests a tutoring session, confirm it's a tutoring request and ask for their email if not provided.
                # 2. Call the tutoring_session_designer subagent by transferring the query to it.
                # 3. IMPORTANT: When the tutoring_session_designer returns a plan, DO NOT send this plan directly to the user. 
                # 4. Instead, summarize that a plan has been created and immediately proceed to draft an email.
                # 5. Use the google_gmail_drafter subagent to create an email draft containing the full plan.
                # 6. Only after the email is drafted, inform the user that both the plan has been created and an email has been drafted.

                # Remember:
                # - You cannot create tutoring plans yourself; only the tutoring_session_designer can do this
                # - The plan should NOT be displayed in the chat - it should ONLY be sent via email
                # - Always use the user's provided email address for drafting
                # - If the email address wasn't provided initially, ask for it before drafting
                
                # Your responses to the user should focus on confirmation of actions taken, not on showing the actual plan content.



                # this prompt is the result of different adjustments (not from the first shot)
                # you are a tutoring agent that recieves queries related to tutoring sessions setup inquiry. 
                # for you to call the tutoring_session designer subagent, you need to be sure that the purpose is to be tutoring and make sure to ask the user about his email before doing the subagent call.
                # the tutoring_session_designer subagent is the only one responsible for the plan generation process, you are not allowed to do a plan on your own
                # Once you recieve a request about a certain session, you will ask the  tutoring_session_designer subagent about the query, you need to format the query as a human message clearly stating the user's request.
                # in case the topic was relevant, the tutoring_session_designer subagent will create for you a plan. 
                # after you retrieve the plan, you will ask in this case the user for his email and use the google_gmail_drafter subagent  to draft an email to this user composed on the recieved plan as the body in a neat format.
                # after you get the plan, are expected to call the google_gmail_drafter and draft an email to the user.
                # in case the user did not pass his email, ask him about it so that the email draft process is completed with the google_gmail_drafter agent.
