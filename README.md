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


### Step 3: Vector Stores and Embeddings

Before doing my research, I was curious why Harrison Chase, Lang Chain’s CEO, was repetitively relied on using chroma vector db integrated with the open ai embeddings in his rag courses. If you go to Lang Chain’s documentation of chroma, you will even notice the following definition for chroma:

* Chroma is a AI-native open-source vector database focused on developer productivity and happiness.

After doing my research, it turned out that chroma is an easy to use vector db that is designed to be used for llm and semantic search ai applications, known for it scalability, and more importantly specifically optimized for storing, indexing, and querying high-dimensional vector embeddings using approximate nearest-neighbor search. But this is not all, the main reason I didn’t even think of trying out other options is the metadata filtering. Chroma stores structured metadata alongside each vector and apply hard filters before vector search where it combine Boolean/meta filters and semantic scores in one pass for precision.

As for the embeddings, I adopted the open ai embeddings, the one Harrison Chase use. It is known that open ai embedding models produce rich, general purpose representations that capture semantic meanings across text, equations, code snippets. Note that I also thought of trying out other embeddings (the GoogleGenerativeAIEmbeddings) but got a Resource has been exhausted error.

### Step 4: Building the RAG

After going through all the previous steps, we need to build our educated rag. For the rag, I had several options to adopts, one of them is the MMR that strives to achieve both relevance to the query to the query and diversity among the results, but that was not my case. I also explored the TFIDF retriever and the SVM retriever, and got exposed to how to combine several techniques using contextual compression retriever that wraps a based retriever (for example vector db with mmr search type retriever) and compresses the results using an llm (compression helps with filtering and refining documents and reordering based on query relevance).

However, none of the above approaches was relevant to my case where I will be capable of educating my search. None except the big guy, the self query retriever, the one that is capable of using our earlier created meta data to filter out where to look based on the user query. In the following figure, you may check the architecture of this retriever and observe its greatness.

<img width="900" height="231" alt="image" src="https://github.com/user-attachments/assets/b98c6585-ff16-4354-8a88-9f82914a89c4" />

Note that for this retriever to perform this search, it needs to be provided with a metadata info field where you describe metadata of your documents.

You may think that this is the end, but no, there is a small present to give. If you want to further refine your results, you might consider adding the early powerful retriever to a conversational chain that will combine the retrieval based methods with conversational capabilities. This chain has an attribute called chain type that determines how retrieved context is combined and reasoned over so that the answers are to answer the question complexity and context size. Note that after conducting some experiments with different chain types retrievals and of course with an llm as a judge, I decided to use the stuff chain type.

For further reference on chain types, you may refer to the following table:

| Chain type            | How it works                                     | Best for                                     | Pros                            | Cons                                           |
| --------------------- | ------------------------------------------------ | -------------------------------------------- | ------------------------------- | ---------------------------------------------- |
| stuff                 | Concatenate all retrieved chunks into one prompt | Few, short, highly relevant chunks           | Fast, cheap, simple             | Token-limit bound; brittle if noisy/long       |
| map\_reduce           | Per-doc answers → combine                        | Cross-doc synthesis, longer contexts         | Scales to many docs; robust     | Slower, pricier; reducer must be well-prompted |
| refine                | Build an answer incrementally doc-by-doc         | Progressive enrichment (tutorials, stepwise) | Captures details as they appear | Order-sensitive; can propagate early mistakes  |
| map\_rerank (scoring) | Per-doc answers + confidence → pick best         | When answer likely in one doc                | High precision; clear source    | Misses answers needing multi-doc synthesis     |

### The RAG Class:

Before creating the rag tool that is to be deployed on the mcp server, I asked chatgpt to wrap my methods in one class, and he did so. What was provided was interesting, he did a metadata filter that can constraint the search by applying a strict metadata filter approach. However, after trying this class, I decided not to use it because although it is not my filter and could not evaluate it properly so that I am in full control of the code. I commented the code in the rag.py file in the rag setup directory in case someone wishes to check it on his own and refine it.

This being said, I want to note that I wrote the other class by myself where I am in full control of the code where I combined the notebook steps together. Also, I could not help but mention what drove me not to use the class I writer is trusting the llm that is in the self query retriever to interpret the natural language hints and not use the metadata hard filters after receiving a query that is un ambiguous at all. Creating this clear query will be explained in details when I dive into the architecture og my llm agent.

### The RAG Tool: 4 tools in 1

After spending too much time building this rag, the rag tool should benefit from every single aspect provided by this educated rag. I want to note before diving into this tool details, I watched a one hour tutorial titled pydantic for llm workflows discussing how to build input and output pydantic models to dictate how you wish your inputs and outputs to be like. You will notice that 2 models were used with the tools itself.

Our rag tool is called probe topic. It has 2 main parameters and one optional parameter (lectures).

The 2 main parameters are the topic and the intent, the topic representing the topic the user is querying (extracted by the llm that uses this tool) and the intent (the most crucial parameter that decides how we are to use our rag). You may notice in the code that we have 5 different intents.

The persense intent: when declared, the rag will check only if the topic is explicitly mentioned in the syllabus. The resources intent: will be called in case the topic is present so that the rag retrieves the lectures that are associated with this topic based on the syllabus. The above two intents will be use by the relevancer agent to check if the topic is present first hand and retrieve its corresponding lectures if so to direct the work of other agents.

The following three intents are similar in functionality, but each has its own scope of search.

The material intent will educate the rag to search only in the chapters metadata (where lectures are found), this will be used by the concept explainer agent to refer to the topic related lectures to answer clarification questions.

The exercises intent is used in case the user wants to practice on some topic. In this case, we will scrape in the assignments (specific to lectures where the topic is present) to generate similar exercises. The tests intent is used in case the user want to have a test, in this case we will scrape the exams to build similar questions. Those two intents will be used by the exercise generator agent. This agent will be supplied with the lectures related to the topic and since the metadata of the assignments are attached to the lectures metadata, the search is made feasible and clear.

### References:

To be capable of doing all the above, there were three tutorials that I used their resources in addition to the langchain docs second hand and some other websites.

* [https://www.deeplearning.ai/short-courses/langchain-chat-with-your-data/](https://www.deeplearning.ai/short-courses/langchain-chat-with-your-data/)
* [https://www.deeplearning.ai/short-courses/langchain-for-llm-application-development/](https://www.deeplearning.ai/short-courses/langchain-for-llm-application-development/)
* [https://www.deeplearning.ai/short-courses/pydantic-for-llm-workflows/](https://www.deeplearning.ai/short-courses/pydantic-for-llm-workflows/)
* [https://www.youtube.com/watch?v=lnm0PMi-4mE\&t=29s](https://www.youtube.com/watch?v=lnm0PMi-4mE&t=29s)
