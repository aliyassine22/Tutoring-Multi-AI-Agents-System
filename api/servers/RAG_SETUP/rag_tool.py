from typing import Literal, Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from . import rag
from pathlib import Path

base_dir = Path(__file__).resolve().parent.parent.parent.parent
course_path = base_dir / "Courses" / "signals and systems"
rag_tool = rag.RAGSearchTool(default_course_path=course_path)

class ProbeArgs(BaseModel):
    topic: str
    intent: Literal["presence", "material", "exercises", "tests", "resources"] = "presence"
    lectures: Optional[List[int]] = Field(default=None, description="Lecture hints; for material we may use the first.")
    k: int = Field(default=15, ge=1, le=50)


class ListingsOut(BaseModel):
    text: str = Field(..., description="Up to k terse lines; agent can display as sources.")



def _probe_topic_fn(topic: str,
                    intent: str = "presence",
                    lectures: Optional[List[int]] = None,
                    k: int = 15) -> Dict[str, Any]:

    # ---- PRESENCE (syllabus only) ----
    if intent == "presence":
        prompt = f"""
You are checking the syllabus for: "{topic}".
if the topic is mentioned in the syllabus, it is covered, else it is not covered.
Respond with STRICT JSON ONLY:
{{
  "covered": <true|false>,
  "note": "<=120 chars brief reason or closest phrasing>"
}}

(No sources, no extra keys.)
""".strip()
        text = str(rag_tool._run(query=prompt, category="syllabus", k=1))
        return {"text": text}

    # ---- RESOURCES (lectures from syllabus) ----
# inside _probe_topic_fn(...)

    if intent == "resources":
        # Syllabus-only; agent will parse this tiny, regular format.
        prompt = f"""
You are given syllabus text with topic headers (e.g., "Fourier Series", "Fourier Transform", etc.)
followed by their lecture numbers.

Task: return the lecture numbers for the given topic: "{topic}"

Rules:
- Work ONLY inside the 'Course Outline' section.
- Collect only the lecture numbers that belong to that section,
  stopping at the next topic header. Ignore any numbers that appear BEFORE the header.
- If multiple chunks are retrieved, merge/deduplicate numbers.
- If no clear match, return NONE.

OUTPUT EXACTLY TWO LINES (no extra text, no quotes, no sources):
LECTURES: <comma-separated lecture numbers as written in the syllabus>
NOTE: <<=120 chars brief reason or closest phrasing>
""".strip()


        text = str(rag_tool._run(query=prompt, category="syllabus", k=5))
        return {"text": text}


    # ---- RETRIEVAL INTENTS (material/exercises/tests) ----
    scope_by_intent = {
        "material": "chapters",
        "exercises": "assignments",
        "tests": "exams",
    }
    scope = scope_by_intent[intent]
    lec_min = None
    lec_max = None
    if lectures and len(lectures) > 0:
        try:
            lec_min = min(lectures)
            lec_max= max(lectures)
        except Exception as e:
            print(f"Error processing lectures: {e}")

    header = f"TOPIC: {topic}\nSCOPE: {scope.upper()}\nFORMAT: Up to {k} terse lines.\n" \
             f"Each line: - Lecture=<N or ?> | Chapter=<N or ?> | <filename> | page=<n> | relpath=<p> | snippet: <≤120 chars>"
    guide = "If a lecture hint is provided, prefer that lecture, otherwise choose best matches."
    prompt = f"{header}\n{guide}"

    text = rag_tool._run(query=prompt, category=scope, lectures=lectures, k=k)
    return ListingsOut(text=str(text)).model_dump()


## useless
probe_topic = StructuredTool.from_function(
    name="probe_topic",
    description=("Educated probe over course corpora.\n"
                 "Intents:\n"
                 "- presence  : syllabus-only coverage → {covered, note} (no sources)\n"
                 "- resources : syllabus-only lecture mapping → {covered, lectures[], note} (no sources)\n"
                 "- material  : chapters-only listings (up to k lines)\n"
                 "- exercises : assignments-only listings (up to k lines)\n"
                 "- tests     : exams-only listings (up to k lines)"),
    func=_probe_topic_fn,
    args_schema=ProbeArgs,
)
