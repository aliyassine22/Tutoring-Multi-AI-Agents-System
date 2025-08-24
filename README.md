## High level architecture
<img width="900" height="343" alt="image" src="https://github.com/user-attachments/assets/8a4574a9-ab02-4dfa-ab01-296146b4e571" />
The tutoring helper is built with LangGraph and searches the course materials using probe topic. It can check if a question is in scope, explain concepts in a grounded way, create practice questions with answers, and produce a short session plan that includes objectives, resources, and durations.

Scheduling is handled by a calendar helper. After the plan is approved, it lists the next available time slots in the student’s time zone and books the selected slot with the summary “Tutoring Session”. There is also support for canceling a booking. An email helper can send a brief confirmation or summary to the studnt when they agree and provide an email address.

The system follows a simple flow: choose a topic, create a plan, show times, book the session, and send an email. It never invents content or availability and never exposes internal tools. All decisions are based on the actual outputs returned by the tools.
## The RAG
For this project, retrieving correct info is more than essential and lies in the core. Thus, it took around 3 days of dedicated work to come with the educated rag search tool. In this section, I will walk through every step I took to come up with this agentic rag and I will cover after wards how my langGraph based agents relied on this tool to perform different meaningful tasks. 

Side note: there is a directory called Rags notebook in my project where I walk you through the steps in my rag buildup journey. Note that in the first two commits you may find some contradictions because I was using this notebook to do prompts hands on experiments that were not so clean. With out further due, let us begin
### Step 0 : Organizing our data
Before loading our data, I organized my data in a way that will make me capable of extracting metadata smoothly in a manner that will be useful in educating my rag search after wards.

Data are not supposed to be loaded randomly, and every sectional organization matters. In the following picture, you may see that my sections are split, and closely related sections were clustered together. 

<img width="159" height="147" alt="image" src="https://github.com/user-attachments/assets/9ca61e92-ffba-42af-ae9e-bead5eb2e3cd" />
In the following picture, you will find a more detailed split at the level of documents, notice how at this level every chapter section is attached to its lectures and the course name.
 <img width="900" height="233" alt="image" src="https://github.com/user-attachments/assets/f74fec70-b594-497c-beac-e824bd8fa3e0" />
The same thing go for the assignments in the assignments directory.
<img width="576" height="29" alt="image" src="https://github.com/user-attachments/assets/5256e031-9aae-406c-8a24-44dcc915e5a1" />

### Step 1: Loading the data
For the loading, I starting initailly with the pypdf loader, however it failed extracting complex patterns related to equations properly (the noise level was high) especially that the structure of the pdf involved complex equations, images-based pdfs, etc. 

After this failure, I searched the possible available loaders and got the pymu pdf loader that can handle my complexities. In the following table, you may find a brief comparison between the 2 loaders in terms of loading complex data:

| Complex-data aspect                          | PyPDFLoader (`pypdf`)                                   | PyMuPDFLoader (`pymupdf`)                                                                     |
| -------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Multi-column & mixed layouts (reading order) | Often jumbles order; no native block/line coordinates   | Much better: returns blocks/lines/spans with bboxes leading to reliable ordering              |
| Tables (gridlines, nested cells)             | Extracts plain text only; hard to reconstruct structure | Block/word bboxes enable downstream table detection (Camelot/heuristics)                      |
| Forms, links, annotations                    | Text only; loses structure                              | Can read annotations/links; keep positions for mapping to text                                |
| Math, symbols, special fonts                 | Can drop ligatures/spacing; loses inline structure      | Better glyph handling; preserves spans so formulas render more coherently (still not perfect) |
| Images & figure captions                     | Can extract some images but no placement                | Extracts images + positions; enables figure–caption pairing                                   |
| Vector graphics & layering                   | Ignored                                                 | Access to drawing objects and layers (useful for layout cues)                                 |
| Large/complex PDFs performance               | Slower; can choke on heavy objects                      | Faster, robust on big/complex docs                                                            |

### Step 1.5: The Metadata?
Managing your metadata is a crucial part of educating your rag search, and unfortunately, tutorials barely focus on this step. When you handle your metadata properly, you are actually giving for every loaded single chunk when you split out your data an identity, every chunk inherits its parent page’s category, chapter, lecture, assignment, exam flags, file name, relpath, etc. When you build the vector store from those chunks, the metadata lives alongside each embedding, thus enabling fine‐grained filtering down to the chunk level (not just whole pages). 
For this project, I stared with a used a method that adds essential metadata only, such as the course id, the category, the chapter, the document id, the filename, and the relative path. However, later on, it came to me that if I want to extend my project further, where we may find ourselves building an ANY COURSE tutoring agent assistant, we need to do enrich our metadata and that’s what happened, I implemented several regex functions that helped me, for every document loaded to:
•	Parse each document’s file path and name to determine its category (e.g., “assignments” vs. “assignments_solutions”).
•	Extract the indexes so that i can later filter or group files by number.
•	Finds all lecture numbers in the filename, then records whether the document covers a single lecture or a range which was the case in most of the times (lecture_min, lecture_max, has_multiple_lectures).
•	Flags solution files (is_solution=True) so that you can treat them differently (e.g., exclude or emphasize solutions).

### Step 2: Splitting the documents
For this step, I was focused on adopting the recursive character based splitter from the beginning after knowing it is very useful with hierarchical splitting and context preservation when we are dealing with complex (after all even the splitter must be compatible with my use case). It is good to mention that I was introduced to this splitter in the langchain rag course offered on deeplearning.ai. 

To make things even clearer, let us elaborate more, using a recursive character based splitter is helpful for complex or heterogeneous documents because:
•	Hierarchical splitting:
 o	It first tries natural breakpoints (e.g. headings, paragraphs, sentences) so you don’t cut equations or code blocks in half.
 o	If a chunk is still too large, it falls back to finer separators (words, then raw characters).
•	Context preservation
 o	You overlap between chunks, so boundary content isn’t lost.
 o	Subsequent LLM calls have enough context to understand continuity across splits.
•	Robustness to varied layouts
 o	Works even when your PDF has images, tables, multi‐column text or unusual formatting.
 o	Ensure each chunk stays under your token limit without arbitrary mid‐sentence cuts.

As for setting the chunk size, this was done after trying different sizes and experimenting with (the judge of the response correctness between rags of different chunk sizes was an llm, for further notice, you may refer to the rag tests notebook). I decided to set the overlap value to be 10% of chunk size, and tried our 3 different chunk sizes (500,1000, 1500). the retrieval with chunk size set to 500 was superior to the 1000 and 1500 ones that tied together in the correctness score. As for why, based on my observation, I would say because the smaller the chunk size the tighter the semantic focus where you will have coherent and consistent ideas together with less noise. Note that also when you increase the chunk size, you need to increase the overlap, thus more duplication. Hence, by setting the chunk size to 500, you are hitting two birds with one stone.
















