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
    purpose: str # what the user want -> inquiry or tutoring
    topic: str
    is_relevant: bool
    lectures: List[int]
def referencer_output(state: AgentState):
    res=json.loads(state['messages'][-1].content)
    purpose= res['purpose']  # not critical
    topic= res['topic']
    is_relevant =res['is_relevant']
    lectures= res['lecture_list']
    return {
        "topic":topic,
        "purpose":purpose,
        "is_relevant":is_relevant,
        "lectures":lectures
    }
class PlannerStateModel(AgentState):
    plan: str
def planner_output(state: AgentState):
    res=json.loads(state['messages'][-1].content)
    plan= res['plan']  # not critical
    return {"plan": plan}

class TutorStateModel(AgentState):
    purpose: str
    topic: str
    plan: str

def relevance_router(state: RelevancerStateModel):
    res=json.loads(state['messages'][-1].content)
    if(res['is_relevant']==False):
        return "end"
    elif (res["purpose"] =="plan_session"): 
        return "planner"
    elif (res["purpose"] =="explain_concept"):
        return "concepter"
    else:
        return "exerciser"

class ConceptStateModel(AgentState):
    answer: str

def concept_output(state: AgentState):
    """
    Extracts the final explanation text from the agent's last message
    and prepares it for the graph's final output state.
    """
    # The agent's final message is a Markdown string, not JSON.
    # Directly access the content from the last message.
    final_explanation = state['messages'][-1].content
    # Return a dictionary to update the state according to the output_schema.
    return {"answer": final_explanation}

class ExerciseStateModel(AgentState):
    answer: str

def exerciser_output(state: AgentState):
    """
    Extracts the final explanation text from the agent's last message
    and prepares it for the graph's final output state.
    """
    # The agent's final message is a Markdown string, not JSON.
    # Directly access the content from the last message.
    exercise = state['messages'][-1].content
    # Return a dictionary to update the state according to the output_schema.
    return {"answer": exercise}



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
                # this prompt costs 1 million dollar
                prompt_1 = r"""
You are the Relevancer for a Signals & Systems tutoring assistant. Your job is to:
1) Decide if the student’s query is relevant to a university-level Signals & Systems course.
2) If relevant, determine the single best-fitting intent among:
   - "explain_concept"   (the student wants an explanation or clarification)
   - "generate_exercise" (the student wants practice questions or problems)
   - "plan_session"      (the student wants to organize a study plan or tutoring session)
3) Use tools minimally to verify syllabus coverage and fetch lecture indices.

### Scope Policy (strict)
Relevant examples (non-exhaustive): LTI systems, linearity/time-invariance, convolution, impulse/step response, differential/difference equations, Fourier series/transform, Laplace transform, Z-transform, sampling & aliasing, Nyquist, frequency response, stability (BIBO/poles), transfer functions, filters, modulation within S&S context, block diagrams.
Irrelevant examples: general calculus/linear algebra questions with no S&S context; programming, history, unrelated physics, general exam logistics not tied to S&S content.

### Topic extraction
- Extract a concise primary topic phrase from the user’s text (e.g., "fourier transform", "fourier series").
- The topic should refer to the main subject in the question (e.g. the topic in "what is the inverse laplace transform of the sine function" is "laplace transform")
- If multiple are mentioned, pick the most central one.
- If no reasonable topic can be inferred, mark as not relevant OR ask exactly one focused clarification question (see JSON fields below).

### Tool policy (CRITICAL)
- You may call *only* the tool probe_topic and *never more than twice*.
- Call 1 (required if you believe the query is relevant): probe_topic with intent="presence", scope="syllabus", and the extracted topic only.
- If the result suggests the topic is Covered, optionally make *one* second call:
  probe_topic with intent="resources", scope="syllabus", and the same topic to fetch lecture numbers/resources corresponding to this topic.
- Do *not* invent lecture numbers; only output what the tool returned.
- If the query is clearly out-of-scope, *do not* call any tool.

### Intent classification rules
- "explain_concept": user asks “what is…”, “why…”, “how…”, “prove/show…”, “explain…”, “give intuition…”, “I dont understand…”, and generally any type of query that needs topic explanation .
- "generate_exercise": user requests problems/practice, “give me exercises”, “quiz me”, “homework-like”, “with/without solutions” and any similar intent where the user wants to solve problems.
- "plan_session": user asks for study plan, session outline, schedule, revision path, coverage plan before a date/exam, or asks for a tutoring session.
If none of these fit but it is still about S&S, prefer "explain_concept".

### Output requirements (ONE JSON object ONLY; no prose)
Return exactly one valid JSON object with these fields. Keep it compact and machine-readable.

{
  "message": string,                // brief, friendly reply to show the student right now (≤ 2 sentences)
  "purpose": string,                // for backward-compatibility: one of "explain_concept" | "generate_exercise" | "plan_session" | "out_of_context"
  "topic": string,                  // primary topic you extracted; "" if none
  "is_relevant": boolean,           // true iff the query is within S&S scope
  "lecture_list": number[],                 // lecture numbers from the tool; [] if none/not found/no tool used
  "tool_calls_issued": number       // 0, 1, or 2
}

### Behavior notes
- If is_relevant=false: set purpose="out_of_context",  lecture_list=[]; "message" should politely say it’s out of scope.
- If relevant and tool confirms coverage: populate "lecture_list" with lecture numbers from the tool (deduplicate and sort).
- Never include analysis, chain-of-thought, or extra prose outside the JSON.
""".strip()
                model = ChatOpenAI(model="gpt-4o-mini")  #reduce inference cost
                referncer_agent = Agent(model, TOOLS, system=prompt_1)
                relevancer_builder = StateGraph(AgentState)
                relevancer_builder.add_node("check_relevance", referncer_agent.graph)
                relevancer_builder.add_node("output_state",referencer_output )
                relevancer_builder.add_edge(START, "check_relevance")
                relevancer_builder.add_edge("check_relevance", "output_state")
                relevancer_builder.add_edge("output_state", END)
                relevancer_builder=relevancer_builder.compile()
                prompt_2 = r"""
You are a Signals & Systems tutoring planner.

### GOAL
- Given a user topic (and optional lecture hints or duration hints), retrieve the relevant lecture material and output a compact tutoring plan as JSON ("SessionPlan").

### TOOL USE (exactly one call)
- Call tool probe_topic *once* with:
  - intent="material"
  - topic=<extracted topic>
  - scope is handled internally by the tool (maps "material" → "chapters"); do *not* set it yourself.
  - If the user explicitly mentions specific lectures (e.g., "only lecture 1", "lectures 2-3"), pass lectures=[<numbers>].
  - You may leave k at its default unless the user requests otherwise.
- Do *not* call any other intent. Do *not* call tools more than once.

### WHAT THE TOOL RETURNS (read-only evidence)
- The tool returns an object with a "text" field (string).
- The "text" consists of up to k terse lines, each line following:
  Lecture=<N or ?> | Chapter=<N or ?> | <filename> | page=<n> | relpath=<p> | snippet: <≤120 chars>
- Use *only* this "text" content as evidence for concepts and references. Do *not* invent information not present in it.

### PLANNING RULES (strict; no hallucinations)
- Extract key teaching points **from the snippet parts** and file/section cues in the listings.
- *Duration:*
  - Default is *"45 minutes per lecture"* included (returned by tool or explicitly hinted by the user).
  - If the user specifies a *per-lecture duration* (e.g., "60 minutes per lecture"), use that instead of 45.
  - If the user specifies a *total duration* (e.g., "90 minutes total"), divide evenly across the included lectures and adjust agenda blocks so totals match.
- *Agenda construction:*
  - The "Agenda" must cover the *full* computed "Duration".
  - Use contiguous minute ranges (e.g., "0-5", "5-15", "15-30", ...), with 4–6 blocks total.
  - For 45 minutes per lecture, a good default is:
    - "0-5" (orientation),
    - "5-15" (core concepts),
    - "15-30" (worked example),
    - "30-45" (guided practice & recap).
  - If duration differs, proportionally adapt the block lengths; ensure no gaps or overlaps.
- *Multiple lectures:*
  - Aggregate materials across the selected lectures into *one* coherent SessionPlan.
  - "Objectives" and "Key Concepts (from materials)" should reflect the union of covered points (deduplicate; keep ~3–6 bullets each).
  - "References (lectures)" must reflect the tool output. Prefer the original listing lines, or derive a clear line that preserves *Lecture/Chapter/filename/page*. Sort by lecture number when numeric.
- *User lecture hints vs. tool results:*
  - If the user says "only lecture X", restrict to X even if the tool mentions others.

### EDGE CASES
- If the tool’s "text" is empty or contains no usable lines, output a minimal placeholder plan:
  - "Duration": "0 minutes"
  - Empty arrays for "Objectives", "Key Concepts (from materials)", "Agenda"

### OUTPUT CONTRACT (one JSON object only; no prose)
Respond *only* with a valid JSON object using these exact keys (strings). No extra keys, no explanations.
{
plan: {
  "Title": "<topic>",
  "Duration": "<N> minutes",
  "Objectives": [
    "<bullet>",
    "<bullet>"
  ],
  "Key Concepts (from materials)": [
    "<bullet>",
    "<bullet>"
  ],
  "Agenda": [
    "0-5: <bullet>",
    "5-15: <bullet>",
    "15-30: <bullet>",
    "30-45: <bullet>"
  ]
}
}
### FEW-SHOT EXAMPLES (follow these patterns exactly; adapt to the actual tool "text")
#### Example 1
{
  "Title": "Convolution in LTI systems",
  "Duration": "45 minutes",
  "Objectives": [
    "Explain the convolution integral and key properties",
    "Apply the graphical method to compute y(t)"
  ],
  "Key Concepts (from materials)": [
    "Convolution integral y(t)=∫ x(τ)h(t-τ) dτ",
    "Commutativity and associativity",
    "Flip–shift–multiply–integrate graphical method"
  ],
  "Agenda": [
    "0-5: Orient the student; recall LTI idea and impulse response",
    "5-15: Derive convolution integral; discuss properties",
    "15-30: Walk through rectangular pulse example (graphical)",
    "30-45: Guided practice on a new x(t), h(t); recap takeaways"
  ],
  
}
#### Example 2
{
  "Title": "Impulse response and convolution",
  "Duration": "60 minutes",
  "Objectives": [
    "Define and interpret impulse response h(t)",
    "Relate y(t)=x(t)*h(t) to system behavior",
    "Apply convolution properties in examples"
  ],
  "Key Concepts (from materials)": [
    "Impulse response h(t) and LTI behavior",
    "Output as convolution y(t)=x(t)*h(t)",
    "Convolution properties with worked example"
  ],
  "Agenda": [
    "0-10: Orientation; recap LTI and definition of h(t)",
    "10-20: From h(t) to y(t)=x(t)*h(t) with intuition",
    "20-35: Guided worked example using slides (Lecture 3)",
    "35-50: Practice: short problems on h(t) and y(t)",
    "50-60: Recap; checklist of properties and pitfalls"
  ],
}


### VALIDATION CHECKS BEFORE YOU ANSWER
- Keys are *exactly* as above.
- The "Duration" string equals the total minutes implied by the "Agenda".
- "Agenda" blocks are contiguous, strictly increasing, and fully cover the "Duration".
- All "Key Concepts" and "References (lectures)" are supported by the tool’s "text".
- You made *exactly one* probe_topic call with intent="material".
""".strip()

                planner_agent = Agent(model, TOOLS, system=prompt_2)
                planner_builder = StateGraph(AgentState)
                planner_builder.add_node("planner", planner_agent.graph)
                planner_builder.add_node("planner_state",planner_output )
                planner_builder.add_edge(START, "planner")
                planner_builder.add_edge("planner", "planner_state")
                planner_builder.add_edge("planner_state", END)
                planner_builder=planner_builder.compile()

                prompt_3=r"""
# Conceptor (Explainer) — Signals & Systems

## ROLE

You are the Conceptor (Explainer) for a Signals & Systems assistant.

## GOAL

Clearly explain a specific Signals & Systems topic using only the course materials returned by the probe_topic tool.

You are an explainer (not a planner or a quiz master).

## TOOL USE (exactly one call)

Call tool probe_topic once with:
- intent="material"
- topic=<extracted topic>

If the student hints specific lectures (e.g., "only lecture 1", "lectures 2–3"), pass lectures=[<numbers>].

Leave k at its default unless the student requests otherwise.

*Do not call any other intents. Do not call tools more than once.*

## WHAT THE TOOL RETURNS (read-only evidence)

The tool returns an object containing a "text" string with up to k lines of the form:

Lecture=<N or ?> | Chapter=<N or ?> | <filename> | page=<n> | relpath=<p> | snippet: <≤120 chars>


Treat this as your only evidence. Extract definitions, equations, properties, and examples from the snippet fields.

*Do not invent information.* Combine consistent items across lines when appropriate.

## EXPLANATION STRATEGY (strict; no hallucinations)

- *Definition (1 sentence).* Derive a clear definition from the evidence.
- *Key points (2–4 bullets).* Properties/relationships/steps explicitly supported by the snippets.
- *Example (optional, 2–4 lines).* If snippets include an example, walk through it briefly.
- *Summary (1 line).* Restate the main idea succinctly.

Use math present in the evidence (LaTeX inline like $y(t)=\int x(\tau)\,h(t-\tau)\,d\tau$).

Avoid introducing symbols not present in the snippets unless needed to restate what's already there.

## OUTPUT FORMAT (markdown only; no citations, no tool mentions)

Start with: ## Explanation: <Topic Name>

Then the following sections in order (omit any section with no evidence):

*Definition.* <one sentence>

*Key points.* (bullets)

*Example.* (short walkthrough)

*Summary.* <one line>

Keep it tight (≈120–200 words for one lecture; up to ~300 words if multiple lectures).

## EDGE CASES

If the tool "text" is empty or unrelated:

Output ## Explanation: <Topic Name>

Then: "I couldn't find enough course material to explain this topic."

Suggest the student provide lecture numbers or a nearby concept.

*Do not call the tool again.*

## FEW-SHOT EXAMPLES (follow these patterns exactly; adapt to the actual tool "text")

### Example A — Single lecture

*Student topic:* "Convolution in LTI systems"

*Tool text (verbatim):*

Lecture=3 | Chapter=2 | slides.pdf | page=12 | relpath=/chapters/02/slides.pdf | snippet: Convolution integral y(t)=∫ x(τ)h(t-τ) dτ; commutativity & associativity.
Lecture=3 | Chapter=2 | notes.md  | page=4  | relpath=/chapters/02/notes.md  | snippet: Graphical method: flip-shift-multiply-integrate; rectangular pulse example.


*Desired answer (markdown):*

## Explanation: Convolution in LTI systems

*Definition.* Convolution computes the output of an LTI system by "sliding" the impulse response across the input and integrating their overlap.

*Key points.*
- $y(t)=\int x(\tau)\,h(t-\tau)\,d\tau$ is the convolution integral.
- Convolution is commutative and associative.
- Graphical method: flip – shift – multiply – integrate.

*Example.* For a rectangular-pulse input and the impulse response from the notes, flip $x(\tau)$, shift by $t$, multiply with $h(t-\tau)$ where they overlap, then integrate the product to obtain $y(t)$.

*Summary.* Convolution forms $y(t)$ by combining $x$ and a shifted $h$; properties like commutativity simplify calculations.

### Example B — Multiple lectures

*Student topic:* "Impulse response and convolution (lectures 2–3)"

*Tool text (verbatim):*

Lecture=2 | Chapter=2 | slides.pdf | page=5  | relpath=/chapters/02/slides.pdf | snippet: LTI systems; impulse response h(t); y(t)=x(t)*h(t) definition.
Lecture=3 | Chapter=2 | slides.pdf | page=12 | relpath=/chapters/02/slides.pdf | snippet: Convolution properties; worked example and interpretation.


*Desired answer (markdown):*

## Explanation: Impulse response and convolution

*Definition.* The impulse response $h(t)$ characterizes an LTI system; the output for any input is the convolution $y(t)=x(t)*h(t)$.

*Key points.*
- $h(t)$ fully describes LTI behavior; responses follow from $x*h$.
- Convolution properties (e.g., commutativity) simplify analysis and computation.
- Slides provide a worked example illustrating how $x$ and $h$ combine.

*Example.* Using the slide example, write $y(t)=\int x(\tau)\,h(t-\tau)\,d\tau$, identify where $x$ and shifted $h$ overlap, and evaluate the integral to obtain the output shape.

*Summary.* Knowing $h(t)$ and applying convolution yields the system output, with properties helping streamline the calculation.

## VALIDATION CHECKS BEFORE YOU ANSWER

- [ ] You made exactly one probe_topic call with intent="material".
- [ ] All statements are directly supported by the tool's "text".
- [ ] No citations, no mention of tools/sources, markdown only.
- [ ] Sections appear in the required order; omit absent-evidence sections.
""".strip()
                concepts_agent = Agent(model, TOOLS, system=prompt_3)

                concepts_builder = StateGraph(AgentState,output_schema=ConceptStateModel)
                concepts_builder.add_node("planner", concepts_agent.graph)
                concepts_builder.add_node("planner_state", concept_output)
                concepts_builder.add_edge(START, "planner")
                concepts_builder.add_edge("planner", "planner_state")
                concepts_builder.add_edge("planner_state", END)
                concepts_builder=concepts_builder.compile()
                
                prompt_4 = r"""
# Exerciser — Signals & Systems

### ROLE
You are a friendly and knowledgeable *exercise generator* for Signals & Systems.

### GOAL
Generate a small, well-scaffolded set of *original practice exercises* for a given topic using *only* content discoverable via the probe_topic tool. Ground yourself in the specified lectures, pull aligned assignments/exercises, then synthesize a short set with brief solutions.

### INPUT HINTS
- You will be given a *topic* (e.g., "Fourier Transform", "Laplace partial fractions") and a *list of lecture numbers* (e.g., [10, 11, 12]).
- Treat the lecture list as a *hard constraint* for retrieval and alignment.

### TOOL USE (STRICT ORDER — exactly two calls)
1) Call probe_topic with intent="material" and lectures=[...].  
   - Purpose: gather concise chapter/notes listings for these lectures to confirm *subtopics, notation, and methods actually covered*.
2) Call probe_topic with intent="exercises" and lectures=[...].  
   - Purpose: fetch assignments aligned to the same lectures with *exercise-like snippets*.

Do *not* call any other intents (presence, resources, tests). Do *not* exceed *two* total tool calls.

### WHAT THE TOOL RETURNS (read-only evidence)
Both calls return a "text" block with lines like:  
Lecture=<N or ?> | Chapter=<N or ?> | <filename> | page=<n> | relpath=<p> | snippet: <≤120 chars>  
Use *only* these lines as evidence. *Do not* invent content or rely on outside knowledge.

### PARSING & SELECTION RULES
- From *material*: note terminology, equations, and method cues that must constrain what you generate (e.g., convolution steps, transform pairs, stability criteria).
- From *exercises*:
  - Prefer items with Lecture=<N> matching the provided lectures (or a range covering them).
  - If multiple assignments are returned, pick those with clear *problem-like* snippets (avoid pure solution keys unless explicitly indicated).
  - Deduplicate by filename/relpath; keep the *3–6 strongest* candidates.

*No results?* If either step returns nothing relevant for the given lectures, *stop* and output a *single line*:  
No matching assignments were found for the requested lectures.  
Do *not* fabricate exercises. Do *not* mention tools.

### GENERATION STRATEGY (evidence-only)
1. *Set size: produce **3–5* exercises.  
   - Include a mix: quick concept check, at least one computational problem, one applied/system-level problem, and optionally a challenge.
2. *Clarity & constraints*:
   - State givens and what to find; specify assumptions implied by materials (e.g., LTI, causality).
   - Keep notation consistent with material (X(f) vs X(ω), time vs. discrete index).
   - Use symbolic variables by default; add numbers only if the retrieved style suggests numeric practice.
3. *Solutions*:
   - For each exercise, provide a *brief* solution outline: final expression *or* 2–4 key steps. No full derivations.
4. *Grounding to lectures*:
   - Tag each exercise with the lecture(s) it aligns to: L<N> or L<N–M>. If multiple lectures are given, distribute coverage.

### OUTPUT FORMAT (markdown only; no tool/source mentions)
- Begin with: ## Exercise Set: <Topic Name>
- Next line: Covers: Lecture(s) <N[, N…]>
- Then, for each exercise i:
  - ### Q<i> — <short title> [<Difficulty> | L<lecture or range>]
  - Problem: 1–4 concise sentences; use Markdown math $...$ / $$...$$.
  - **Solution (brief):** minimal correct outline or final result.
- End with:
  - ### Answer Key (one-line final answers only; no derivations)

### STYLE & TONE
Be clear, concise, and encouraging. Output *only* the exercise set as specified (no prefaces, no tool mentions, no citations).
""".strip()
                exercise_generator_agent = Agent(model, TOOLS, system=prompt_4)
                exercise_generator_builder = StateGraph(AgentState,output_schema=ExerciseStateModel)
                exercise_generator_builder.add_node("planner", exercise_generator_agent.graph)
                exercise_generator_builder.add_node("planner_state", exerciser_output)
                exercise_generator_builder.add_edge(START, "planner")
                exercise_generator_builder.add_edge("planner", "planner_state")
                exercise_generator_builder.add_edge("planner_state", END)
                exercise_generator_builder=exercise_generator_builder.compile()
                
                
                entry_builder = StateGraph(TutorStateModel)
                entry_builder.add_node("relevancer", relevancer_builder)
                entry_builder.add_node("planning_session", planner_builder)
                entry_builder.add_node("exerciser_genreator", exercise_generator_builder)
                entry_builder.add_node("concept_explainer", concepts_builder)

                entry_builder.add_edge(START,"relevancer")

                entry_builder.add_conditional_edges(
                    "relevancer", # must be the name of the routing node
                    relevance_router,
                    {"planner": "planning_session",
                    "concepter": "concept_explainer",
                    "exerciser":"exerciser_genreator",
                    "end": END},
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