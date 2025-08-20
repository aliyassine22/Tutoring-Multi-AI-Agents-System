import os, sys
import openai
from pathlib import Path
import threading
import operator
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field, PrivateAttr
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import DirectoryLoader, PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.chains.query_constructor.schema import AttributeInfo
from typing import Literal, Dict, Any, List, Optional, Annotated, Type, TypedDict
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
import json, re
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from mcp import ClientSession
from mcp.client.sse import sse_client
from langgraph.graph import StateGraph, START, END
from langchain_mcp_adapters.tools import load_mcp_tools
import asyncio


# In langGraph.py, add a connection manager
class MCPConnectionManager:
    def __init__(self):
        self.session = None
        self.client = None
        self._initialized = False
    
    async def initialize(self):
        if self._initialized:
            return self.session
        
        # Create connection that stays alive
        self.client = sse_client("http://127.0.0.1:8787/sse")
        read_stream, write_stream = await self.client.__aenter__()
        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()
        await self.session.initialize()
        self._initialized = True
        return self.session

# Create a global instance
connection_manager = MCPConnectionManager()


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
class Agent:

    def __init__(self, model, tools, system=""):
        self.system = system
        graph = StateGraph(AgentState)
        graph.add_node("llm", self.call_openai)
        graph.add_node("action", self.take_action)
        graph.add_conditional_edges(
            "llm",
            self.exists_action,
            {True: "action", False: END}
        )
        graph.add_edge("action", "llm")
        graph.set_entry_point("llm")
        self.graph = graph.compile()
        self.tools = {t.name: t for t in tools}
        self.model = model.bind_tools(tools)

    def exists_action(self, state: AgentState):
        result = state['messages'][-1]
        want_tools = isinstance(result, AIMessage) and bool(getattr(result, "tool_calls", None))
        return  want_tools

    async def call_openai(self, state: AgentState):
        messages = state['messages']
        if self.system:
            messages = [SystemMessage(content=self.system)] + messages
        message = await self.model.ainvoke(messages) # aynchronous invoke
        return {'messages': [message]}

    async def take_action(self, state: AgentState):
        tool_calls = state['messages'][-1].tool_calls
        results = []
        for t in tool_calls:
            print(f"Calling: {t}")
            if not t['name'] in self.tools:      # check for bad tool name from LLM
                print("\n ....bad tool name....")
                result = "bad tool name, retry"  # instruct LLM to retry if bad
            else:
                result = await self.tools[t['name']].ainvoke(t['args']) # aynchronous invoke
            results.append(ToolMessage(tool_call_id=t['id'], name=t['name'], content=str(result)))
        print("Back to the model!")
        return {'messages': results}

async def run_single_graph_test(graph, query: str):
    payload = {"messages": [HumanMessage(content=query)]}
    print(f"--- Invoking graph with query: '{query}'")
    out = await graph.ainvoke(payload)
    print(f"--- Graph invocation complete.")
    return out
class RelevancerStateModel(AgentState):
    purpose: str
    topic: str
    is_relevant: bool
    lectures: List[int]
def referencer_output(state: AgentState):
    try:
        res=json.loads(state['messages'][-1].content)
        purpose= res.get('purpose', '')  # not critical
        topic= res.get('topic', '')
        is_relevant =res.get('is_relevant', False)
        lectures= res.get('list', [])
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing referencer output: {e}")
        # Just continue with the state as is
    return state
class PlannerStateModel(AgentState):
    plan: str
def planner_output(state: AgentState):
    try:
        res=json.loads(state['messages'][-1].content)
        plan= res.get('plan', '')  # Use .get() with default empty string
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing planner output: {e}")
        # Just continue with the state as is
    return state
class TutorStateModel(AgentState):
    purpose: str
    topic: str
    plan: str

def relevance_router(state: TutorStateModel):
    try:
        # Access the last message from the state
        res=json.loads(state['messages'][-1].content)
        if(res.get('is_relevant', False)==False):
            return "end"
        else: 
            return "planner"
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing router state: {e}")
        return "end"  # Default to end if parsing fails
    
async def main(session):
    try:
                sys.path.append('../..')
                from dotenv import load_dotenv, find_dotenv
                _=load_dotenv(find_dotenv()) # read local .env file
                openai.api_key =os.environ['OPENAI_API_KEY']

        # the following two lines are game changers
        # async with sse_client("http://127.0.0.1:8787/sse") as (read_stream, write_stream):
        #     async with ClientSession(read_stream, write_stream) as session:
                # session = await connection_manager.initialize()

                tools = await load_mcp_tools(session=session)
                tool_map = {tool.name: tool for tool in tools}
                TOOLS= [tool_map['probe_topic']] # trying the server after trying the enhanced rag class

                prompt_1 = (
            "You are a Signals & Systems tutoring assistant that check if the topic present in the user query is relevant to the course.\n"
            "If the user is greeting you, greet him back, set the topic to greeting, irrelevant to true, and the purpose to out of context\n"
            "If the question is irrelevant to the signals and systems engineering topic, respond to the user by stating that you are only a signal and systems assistant. \n"
            "In case the question was relevant to the signals and systems engineering topic, follow the following workflow. \n"
            "Workflow:\n"
            "1) Call tool probe_topic once with intent='presence' and scope='syllabus'. The topic must be extracted from the user\n"
            "2) If the summary suggests Covered , call probe_topic again with intent='resources' "
            "   and scope='syllabus'.\n"
            "3) Then STOP using tools. Reply briefly with:\n"
            "   - topic: string stating what was the topic the user was asking about\n"
            "   - is_relevant: boolean that is set to true if the topic is found\n"
            "   - If found: list lecture numbers in a list called list\n"
            "   - purpose: string representing the user purpose, can be either one of three, either \"tutoring\" or \"topic general question\" or \"out of context\", depending on the query. note that every question outside the scope of the signal and systems engineering topic is considered \"out of context\", not \"general question\". \"general question\" catergory represent the questions related to the signals and systems topic.\n"
            "Never call the tool more than twice.\n"
            """ Return ONE valid JSON object ONLY, no prose.
                Required JSON shape:
                {
                "message": string,              // your response to the user query
                "purpose": string,              // natural question or tutoring request
                "topic": string,               // the topic the user is asking about
                "is_relevant": boolean,        // true iff the topic is found
                "list": number[]               // lecture numbers where the topic appears; [] if none/not found
                }
            """
                ).strip()

                model = ChatOpenAI(model="gpt-4o-mini")  #reduce inference cost
                referncer_agent = Agent(model, TOOLS, system=prompt_1)
                relevancer_builder = StateGraph(AgentState)
                relevancer_builder.add_node("check_relevance", referncer_agent.graph)
                relevancer_builder.add_node("output_state",referencer_output )
                relevancer_builder.add_edge(START, "check_relevance")
                relevancer_builder.add_edge("check_relevance", "output_state")
                relevancer_builder.add_edge("output_state", END)
                relevancer_builder=relevancer_builder.compile()

                prompt_2 = ( """
        You are a Signals & Systems tutoring planner.

        Goal:
        - Given a user topic, retrieve relevant lecture material and output a compact tutoring plan as JSON (SessionPlan).

        Tool use (exactly 1 call):
        - Call tool `probe_topic` ONCE with intent="material".
        - If the user hints specific lectures (e.g., "only lecture 1" / "lectures 2-3"), pass lectures=[...] to the tool.
        - In case of multiple lectures hinted, you are to generate a plan for the lectures.
        - Do not call any other intents. Do not call tools more than once.

        How to plan:
        - Read ONLY the tool’s returned text (listings) as your evidence.
        - Derive key teaching points present in the sources (don’t invent).
        - Build a 45 minute plan for every lecture, by default unless the user specifies duration.
        - In case of multiple lectures, overall plan duration is equal to the number of lectures multiplied by 45 mins for each lecture,

        Output:
        - Respond only with a valid JSON matching the SessionPlan schema (no extra keys, no prose).
        - for the SessionPlan schema, follow the following format (exact section headers):
            Title: <topic>
            Duration: <N> minutes
            Objectives:
            - <bullet>
            - <bullet>
            Key Concepts (from materials):
            - <bullet>
            - <bullet>
            Agenda:
            - 0–5: <bullet>
            - 5–15: <bullet>
            - 15–30: <bullet>
            - 30–45: <bullet>
            - 45–60: <bullet>
            Active Practice:
            - <bullet>
            - <bullet>
            References (lectures):
            - <lecture ref from tool output>
            - <lecture ref from tool output>
        """
                    ).strip()
                planner_agent = Agent(model, TOOLS, system=prompt_2)
                planner_builder = StateGraph(AgentState)
                planner_builder.add_node("planner", planner_agent.graph)
                planner_builder.add_node("planner_state",planner_output )
                planner_builder.add_edge(START, "planner")
                planner_builder.add_edge("planner", "planner_state")
                planner_builder.add_edge("planner_state", END)
                planner_builder=planner_builder.compile()

                entry_builder = StateGraph(TutorStateModel)
                entry_builder.add_node("relevancer", relevancer_builder)
                entry_builder.add_node("planning_session", planner_builder)

                entry_builder.add_edge(START,"relevancer")

                entry_builder.add_conditional_edges(
                    "relevancer", # must be the name of the routing node
                    relevance_router,
                    {"planner": "planning_session", "end": END},
                )
                entry_builder.add_edge("planning_session", END)
                graph = entry_builder.compile()

                # response = await run_single_graph_test(graph, "i want to reserve a session on fourier series?")
                # print(response['messages'][-1].content)
                return graph
    except Exception as e:
        print(f"Error in main(): {e}")
        import traceback
        print(traceback.format_exc())
        raise  # Re-raise to prevent returning None
# graph =asyncio.run(main())
# if __name__ == "__main__":
#     asyncio.run(main())