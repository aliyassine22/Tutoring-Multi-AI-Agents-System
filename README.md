## High-Level Architecture

<img width="900" height="343" alt="image" src="https://github.com/user-attachments/assets/8a4574a9-ab02-4dfa-ab01-296146b4e571" />

The tutoring helper is built with **LangGraph** and searches the course materials using `probe_topic`. It can check if a question is in scope, explain concepts in a grounded way, create practice questions with answers, and produce a short session plan that includes objectives, resources, and durations.

Scheduling is handled by a calendar helper. After the plan is approved, it lists the next available time slots in the student’s time zone and books the selected slot with the summary **“Tutoring Session.”** There is also support for canceling a booking. An email helper can send a brief confirmation or summary to the student when they agree and provide an email address.

**Flow:** choose a topic → create a plan → show times → book the session → send an email.
The system never invents content or availability and never exposes internal tools; all decisions are based on actual tool outputs.

---

## The RAG

Retrieving correct information is core to this project. It took \~3 days of focused work to design the RAG search tool. Below, I walk through the steps used to build the agentic RAG and how the LangGraph-based agents rely on it for meaningful tasks.

*Side note:* see the **RAGs notebook** directory for a step-by-step build. Early commits may contain rough prompt experiments.

### Step 0: Organizing the Data

Before loading, the data was structured to enable smooth metadata extraction that would later “educate” the RAG search.

Data is not loaded randomly—sectional organization matters. In the image below, related sections are clustered:

<img width="159" height="147" alt="image" src="https://github.com/user-attachments/assets/9ca61e92-ffba-42af-ae9e-bead5eb2e3cd" />

At the document level, each chapter section is attached to its lectures and course name:

<img width="900" height="233" alt="image" src="https://github.com/user-attachments/assets/f74fec70-b594-497c-beac-e824bd8fa3e0" />

The same applies to the **assignments** directory:

<img width="576" height="29" alt="image" src="https://github.com/user-attachments/assets/5256e031-9aae-406c-8a24-44dcc915e5a1" />

### Step 1: Loading the Data

I initially used the **PyPDF** loader, but it struggled with complex equations and image-heavy PDFs (high noise). I switched to **PyMuPDF**, which handled these complexities much better.

**Brief comparison for complex data:**

| Complex-data aspect                          | PyPDFLoader (`pypdf`)                                   | PyMuPDFLoader (`pymupdf`)                                                                     |
| -------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Multi-column & mixed layouts (reading order) | Often jumbles order; no native block/line coordinates   | Much better: returns blocks/lines/spans with bboxes leading to reliable ordering              |
| Tables (gridlines, nested cells)             | Extracts plain text only; hard to reconstruct structure | Block/word bboxes enable downstream table detection (Camelot/heuristics)                      |
| Forms, links, annotations                    | Text only; loses structure                              | Can read annotations/links; keep positions for mapping to text                                |
| Math, symbols, special fonts                 | Can drop ligatures/spacing; loses inline structure      | Better glyph handling; preserves spans so formulas render more coherently (still not perfect) |
| Images & figure captions                     | Can extract some images but no placement                | Extracts images + positions; enables figure–caption pairing                                   |
| Vector graphics & layering                   | Ignored                                                 | Access to drawing objects and layers (useful for layout cues)                                 |
| Large/complex PDFs performance               | Slower; can choke on heavy objects                      | Faster, robust on big/complex docs                                                            |

### Step 1.5: Metadata

Managing metadata is crucial for an effective RAG. Each chunk inherits its parent page’s metadata (category, chapter, lecture, flags, filename, relpath, etc.). When the vector store is built, this metadata lives alongside embeddings, enabling fine-grained filtering at the **chunk** level.

I started with essentials (course ID, category, chapter, document ID, filename, relpath), then enriched the schema using regex helpers to:

* Parse file paths/names to determine category (e.g., `assignments` vs `assignments_solutions`).
* Extract indexes to later filter/group by number.
* Detect lecture numbers and record single vs range coverage (`lecture_min`, `lecture_max`, `has_multiple_lectures`).
* Flag solution files (`is_solution = true`) to handle them differently (e.g., exclude or emphasize).

### Step 2: Splitting the Documents

I used a **recursive character splitter** for hierarchical splitting and context preservation (introduced in the LangChain RAG course on deeplearning.ai):

* **Hierarchical splitting**

  * Prefers natural breakpoints (headings, paragraphs, sentences) to avoid cutting equations/code.
  * Falls back to finer separators (words → characters) only when needed.
* **Context preservation**

  * Overlaps between chunks so boundary content isn’t lost.
  * Ensures downstream LLM calls see enough context.
* **Robustness to varied layouts**

  * Works with images, tables, multi-column text, and unusual formatting.
  * Keeps chunks under token limits without mid-sentence cuts.

**Chunking choices:** overlap set to **10%** of chunk size. I tested sizes **500**, **1000**, and **1500** tokens; **500** performed best (tighter semantic focus, less noise). Larger chunks also require larger overlaps, increasing duplication—another reason to prefer 500 here.
