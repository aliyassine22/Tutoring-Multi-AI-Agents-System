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


## Building our LangGraph based agents:

With the rag tool ready, I created specialized agents, each with a distinct role and a tailored way to invoke the tool, using LangGraph’s React architecture. The approach to build the react agent is from the AI Agents in LangGraph tutorial and will be the standard pattern which will be followed for all our agents. The whole point of using this approach was to add flexibility to my agents. After all, I started initially by using the create\_tool\_calling\_agent built in method that attaches a llm with a tool and then wrapped it using them together using agent executor class (you may check the results in the rag notebook).
As for the adopted react agent, you may find the architecture in the following figure:

<img width="310" height="373" alt="image" src="https://github.com/user-attachments/assets/47c13967-b997-488e-acf5-39aa52eba36b" />


Briefly going over the architecture, this agent is composed of two main nodes, the llm node were the model that is bound to tools reads the accumulated messages, injects the system prompt once, and either answers directly or emits structured tool\_calls. As for the tools node, it executes those calls, returns tool messages and loops control back to the llm  until no further actions are needed.
Now for our agents, I built an independent graph for every agent although the graph implementation was given with react agent, all for the sake of having structured outputs for every agent. Please find the architecture of our LangGraph based tutoring agent in the following figure:

<img width="698" height="369" alt="image" src="https://github.com/user-attachments/assets/9504a740-e20b-4cd1-a9f2-3fb0ed0b95eb" />

The above graph represents a high level view of our tutoring agent.

### Relevancer agent

The relevance agent is the one that will check if the topic that the user is interested in is relevant to the course, based on the user query and his topic relevance, the conditional edge afterwards will determine whether to router the query to some other agent and educate the search or to end the whole process in case of irrelevancy. The whole point of this agent is to guide our search and to prevent the waste of resources. The output of this agent will be as in the following sample where the user is querying about a z transform fourier session:

<img width="900" height="144" alt="image" src="https://github.com/user-attachments/assets/afab6b7a-5a93-4732-841a-16e9f6bba0a6" />

Let us look at this output together so that we may have an insight on how the work of the following agents will be guided. Based on the purpose of the root agent (the one calling the whole langGraph agentic flow), we will know to which agent the query is to be forwarded in case the topic was relevant, as for the lecture list, it represents the lecture where the topic is discussed. The tool calls issued parameter was used for me to check if the model is calling the tool the way I instructed in the prompt and a sanity check at the same time.
What is great of the above output is that it was captured when I had two issues. The first was that the vector db was full of duplicates (4 or 5) because I loaded the documents every time the kernel restarted (at that point, I realized that I need to load embedding from the db instead of adding them all over again and did directly add the load from db method in the rag class). The second reason, which is the most crucial, was the prompt. I was not clear and the prompt was instructing the rag to get the lectures where the topic is first mentioned, not where the topic is discussed in details in the syllabus. I managed to solve both issues later on. In the notebook, you will see me trying different prompts (I recorded some trials but got bored after all, so I started refining directly). There will be a section where I will discuss my prompt template that I finally relied on and was exceptional in every possible way, stay tuned.
Spoiler alert, this is the correct output I have got after fixing my prompt.

<img width="900" height="149" alt="image" src="https://github.com/user-attachments/assets/6aba7da1-6336-49ea-ae8e-c8cb5fe78426" />

### Planner agent

As for the second agent, the planner, this agent will create a plan for tutoring session after scraping the lectures that are handed from the relevancer agent related to the user topic and send this plan for approval.
Note that this agent, as it is with the other agents, is a subgraph because it has a unique output. I find it useful here to advice those who want to have a well formatted formats to use a markdown based outputs instead of a json based one as I did with the planner in case the output of the agent is to be returned to the user and not further interpreted.
Below is a sample output from the planner agent:

<img width="900" height="476" alt="image" src="https://github.com/user-attachments/assets/2100e96c-103f-4129-9793-0afe5ecdc2c4" />

### When to format Note

•	In case your output is to be returned to the user, adopt a markdown format in your prompt as I did with the concept explainer and the exercise generator agent and must have done with the planner agent instead of formatting the json output which happened to be useless.
•	In case your output is to be used by other agents in a sequential workflow, it must be in a json format so that you are to extract useful info and pass it down to those agents to use, there is no other choice.

### Conceptor agent

This agent relies on topic related lectures to answer the user inquiry questions. Similar to the planner, this agent calls the probe topic (rag tool ) only once and returns a clarification that is well formatted. Here is a sample output in a markdown format:

<img width="900" height="206" alt="image" src="https://github.com/user-attachments/assets/31ddcf88-1dcf-414b-b26e-f1fe9f3407d2" />

Note that this format will be read properly on our frontend and will be shown at the end of this readme in the demo section

### Exercise generator agent

This guy calls the probe topic tool twice, the first to scrape the lectures for the assignment’s information, and the second to scrape the assignments and get relevant exercises. I would have also further extended this agent with an option to scrape exams, however I got shortened on time. To do so, the prompt will need to be updated in the following manner so that the agent will follow also 2 tool calls strategy but of course with an addition of an extra flag in the relevancer agent called scrape\_test. The prompt will be extended to the current version to accommodate to this parameter, in case the flag is set to false, the current workflow will be undergone. However, if the flag is true, we will need to call our probe tool in a different strategy where the first call will be with scope syllabus and intent material to check for the exams’ questions related to the topic and the second with intent tests to go over the tests and retrieve relevant samples.
This is a sample output of our exercise generator in a markdown format:

<img width="1080" height="509" alt="image" src="https://github.com/user-attachments/assets/8e162375-819c-4d5e-ba46-884056ebd532" />

### Building the whole thing

After building those subgraphs, I put them all together in the graph shown above. This process of putting subgraphs together is adopted in large and complicated projects to enable powerful pipelines. My primary motivation was to reuse a single Agent class for all four roles. Since each agent has a unique output schema, I wrapped each one in a dedicated subgraph. This allowed me to add a final node to each subgraph responsible for parsing the agent's specific output and updating the main graph's state accordingly.
In the following image, you will observe two subgraphs (relevancer and planner) joined together to have a better understanding of what is being proposed.

<img width="494" height="1331" alt="image" src="https://github.com/user-attachments/assets/4e443f72-fe71-4956-90cf-4d397e7d3393" />

### Final note

At the stage of building prompts, I did not have enough time to record every change I did and every trial because I was losing time. At that stage and after finding the prompt template to adopt, my whole purpose was to make things work. In the rag notebook, things turned out to be messy as we tend to the end because I was running different cells in different orders only for the sake of testing, that’s why you might find it hard to follow up with the rag notebook as it tend to the end unless you run it in order. I apologize for confusion. You may find my first developed prompts before getting the prompt schema and adopting and tweaking it in the builder notebook.
The changes to the prompt template were done directly in the buildup and were not recorded due to the deadline emerging and full focus on developing an ultimate working product. The template will be provided and explained so that others may benefit from it in another section (working with the prompt was the most stressful and thrilling thing that I have done throughout this project).

### References

[https://www.deeplearning.ai/short-courses/ai-agents-in-langgraph/](https://www.deeplearning.ai/short-courses/ai-agents-in-langgraph/)
[https://academy.langchain.com/courses/take/intro-to-langgraph](https://academy.langchain.com/courses/take/intro-to-langgraph) , specifically module 2 and 4
note that the source codes of each course are downloaded locally. 

## ADK based agents

### General Overview

For our adk agents, I wanted to adopt a high level structure that will utilize the power of the google open api. For that reason, I decided to ensure the user communication track with the tutoring agent acting on behalf of the tutor via google gmail and calendar tools.

### Calendar Agent

The calendar agent plays a vital role in this vision, as it is the agent that will give out to the user’s necessary information about the available sessions and book or cancel the sessions for them. For this purpose, the calendar agent had access to two main tools to use (it has 4 tools attached and will explain the purpose each one).

#### List events tool

This tool will scrape the calendar for the available tutoring sessions to return them to the users.

#### Update event tool

Once the user decides on an available tutoring session, this tool will change the title of that event to tutoring session and add a brief description about the topic in addition to the user email.
Now for the tools that might be integrated for different purposes

#### Delete event tool

This tool was to be used in one scenario, in case the user want to unbook in a 6 hours range pre the session for some reason, it will delete the event and send the tutor a deletion note from the student or perhaps a rescheduling note.

#### Create event tool

This tool in case it is to be used is to be used by the tutors not the students, so currently it has no available use case. However, if we decided to extend this agent into a full scaled product that works with both parties (tutors and students, not only students), this tool will be of great benefit. To be honest, I only used this tool in the current scenario so that an agent creates the available tutoring session events on my behalf (I did not want to do this process manually).

### Gmail Agent

This agent will be the one responsible for sending emails of the plan accompanied by the meeting link to the students using the send email tool. Note that I had initially a different vision for this agent, that is it draft emails for the tutor with the plan embedded with them and the tutor in this case will need only to send (him sending the email is the approval). However, if we investigate things from a broader perspective, we will notice that the student is more familiar with what he needs to be tutored on, thus it would be more reasonable for the plan once approved by the student to be sent directly to the student. Hence, the draft email (for the tutor) tool was changed to the send email (to the student) tool.

### Crucial Gap: authentication

On medium, the following website discusses how to build up this structure in a way where you import the tools directly from google using the apis’ scopes only. Unfortunately, I spent nearly 6 hours trying to make their approach work but did not do so. Moreover, on that website, the author suggests a solution for authentication where the user will only authenticate once (I tried it his way but failed miserably). After that, I decided to build in the tools myself using the google gmail api docs and the google calendar api docs and did everything by self in less than 1 hour.
As for the authentication issue (you need to authenticate every time you want to use a google api call), I discussed the current problem with Mr. Roy Daher, the devops track instructor at inmind, and suggested that to do this properly I need a robot agent that handles only authentication. This approach happened to be time consuming and based on Roy’s advice, I had to skip it to make the full product work as whole.

#### Current authentication approach:

Whenever a user calls a Google API, they must authenticate. According to the joogle API docs, you should place a credentials.json file (your OAuth client credentials) in the same directory as your application. After the first sign-in, the library creates a token.json file that stores the user’s access and refresh tokens. If this file is present and valid, the app can make subsequent requests without prompting the user to authenticate again. Since it is more likely for tokens to expire or become invalid, I always insured the authentication will take place whenever a google tool call is issued.

\###Note
The progress that was made and the way I developed and tested the tools one by one can be tracked by referring to the adk agents notebook.

### References:

[https://developers.google.com/workspace/gmail/api/guides](https://developers.google.com/workspace/gmail/api/guides)
[https://developers.google.com/workspace/calendar/api/guides/overview](https://developers.google.com/workspace/calendar/api/guides/overview)
medium article (waste of time): [https://medium.com/google-cloud/building-a-multi-agent-application-to-interact-with-google-products-b7ff7eb2f17d](https://medium.com/google-cloud/building-a-multi-agent-application-to-interact-with-google-products-b7ff7eb2f17d)

## Deployment on MCP server

Those tools in addition to the probe topic tool (rag tool) were deployed on an fast mcp server running with server sent events for transport where they are made available to different agents. Note that calling the tools by adk agents is a simple process that requires no more than using the mcp tool set with an sse connection object and a tool filter. However, it took me some time to figure out how to connect the langGraph based agents to their probe tool while enabling the a2a protocol.
 

## A2A Protocol

For setting up the a2a protocol, I referred first to a youtube tutorial to understand the intuitions behind this protocol and review the implementation. After that, my colleague at inmind academy Mohamad Shoeib referred me to a robust medium article that provides the general structure for the a2a communication protocol. Note that I had to introduce some changes to the code to make it compatible with my case.
This a2a server implementation provides a web interface for our langGraph based agent. It begins by defining an agent card, which acts as a public profile, advertising the agent's name, capabilities (streaming), and specific skills. The core of the server is the A2AStarletteApplication that listens to http requests and passes them to the default DefaultRequestHandler that uses a custom LanggraphAgentExecutor to manage the actual task execution. When a user query is received, the executor streams the input into the langGraph agent, which maintains conversational state using a thread id. As the graph processes the request through its various nodes, the executor uses an event queue and a task updater to send real time progress messages back to the client, finally delivering a completion message when the graph reaches its end state.
Our langGraph agent was successfully deployed on an a2a server following the above process, but throughout this integration I faced an issue with the langGraph agent being unable to connect to the mcp server. I got this error because I thought the notebook practices in calling tools after connecting the mcp session can be applied directly when invoking the same functionalities in the python file. This confusion took me a while to catch, it is working there but not here, why so?
At the beginning, I thought that the error is due to timeouts, so I insured the timeout was more than sufficient, but that was not the case. The case was due to losing connection to my mcp server when I instantiate my langGraph based agent. To fix it, one must ensure that the mcp server is instantiated outside of the method that returns langGraph and before this method is called, and that is exactly what happened.
There is one more thing that I cannot avoid mentioning, that is the astream method that provides an asynchronous way to stream outputs from a graph execution. In this method, you may notice that I have set the stream mode to values. This was done so that a complete snapshot of the entire graph's state is returned after each node executes, thus making tracking feasible. In contrast, modes like 'updates' or 'messages' would only provide partial information, such as the output of the last node, preventing this level of stateful tracking.
 
Now that our langGraph based agent is successfully deployed using an a2a server, what is going to happen next is that we will connect our orchestrator, an adk based root agent with having the calendar and gmail agents as subagent with our langGraph agent (the prime agent) as a subgraph.
Note that the adk agents were created in the same file as the orchestrator.
In the next section, I am going to discuss the prompt template that I have adopted with my agents.

## References

The following references where mainly used in the development of the adk agents and the mcp and a2a protocol.
[https://www.youtube.com/watch?v=P4VFL9nIaIA](https://www.youtube.com/watch?v=P4VFL9nIaIA)
[https://github.com/bhancockio/agent-development-kit-crash-course](https://github.com/bhancockio/agent-development-kit-crash-course)
[https://www.youtube.com/watch?v=mFkw3p5qSuA](https://www.youtube.com/watch?v=mFkw3p5qSuA)
[https://medium.com/@aditya\_shenoyy/google-a2a-enabling-existing-langgraph-agents-to-work-with-the-google-a2a-protocol-using-adk-6358e08cae6d](https://medium.com/@aditya_shenoyy/google-a2a-enabling-existing-langgraph-agents-to-work-with-the-google-a2a-protocol-using-adk-6358e08cae6d)
[https://www.youtube.com/watch?v=HkzOrj2qeXI](https://www.youtube.com/watch?v=HkzOrj2qeXI)
 

## Prompt template

The changes that were introduced to each prompt, especially the one of the orchestrator, would take forever to discuss. In this section, I will discuss the structure of the main prompt used in case anyone would like to use it in his project.

<img width="900" height="697" alt="image" src="https://github.com/user-attachments/assets/e7806b03-18fd-4c15-9dbd-2d6d112c3ecb" />

This is a brief explanation for each section in the prompt in case you are interested:

| Component                        | Explanation & supporting evidence                                                                                                                                                                                                                                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Role / Mission                   | Defines who the model is and what success looks like. This sets the persona and scope.                                                                                                                                                                                                                                   |
| Goal / Intent                    | Articulates the deliverable or success criteria. A prompt stack begins with the intent, the goal, target audience and success criteria.                                                                                                                                                                                  |
| Tool use                         | Specifies which tools the model is allowed to call and how to use them. System prompts should list allowed tools and usage rules, and a prompt stack includes a tool catalog with names, purpose, input/output schema and limits. The “capabilities” layer of context engineering includes tool definitions and schemas. |
| What the tool returns            | Clarifies that tool outputs become part of the context. When an agent calls a tool, the result (data payload or error) is fed back into the context window as an observation. The prompt schema should explain that returned values serve as evidence for the model’s next step.                                         |
| Task rules / Reasoning mode      | Outlines the step by step method or reasoning mode. Production architectures separate planning, execution and checking; planners decompose tasks and define success criteria, executors call tools, and checkers validate results. System prompts often instruct the model to plan first, then act.                      |
| Approval & Clarification         | States when and how the agent should ask the user for clarification. System prompts may include an escalation rule: when unsure, ask one clarifying question. MCP documentation notes that tools may need to ask clarifying questions or require human approval before completing operations.                            |
| Routing / Decision guide         | For agents controlling multiple models or tools, the prompt stack uses routers and controllers to decide which pattern or tool to invoke. The controller orchestrates steps and chooses patterns like zero shot, chain of thought or tool first strategies.                                                              |
| State / Context rules            | Defines how to manage memory and context. Context engineering treats short term memory (recent conversation), long term memory (persistent user data) and retrieved documents as layers. Best practices include writing to scratchpads, selecting relevant memories, compressing context and isolating sub agents.       |
| Edge cases / Error handling      | Prompts should specify how to handle empty or conflicting inputs. Anthropic engineers advise testing prompts against edge cases—unexpected or incomplete inputs—and instructing the model to return an “unsure” tag when uncertain. This prevents the model from guessing.                                               |
| Output format / Contract         | The system prompt should define the output contract—JSON schema or markdown—and include examples. The prompt stack’s output contract layer requires a machine checkable schema with citations and confidence.                                                                                                            |
| Validation checks                | High quality agents include a verification layer that uses checklists, schema validation and policy tests to ensure outputs conform to the contract. This layer catches hallucinations or policy violations before returning the response.                                                                               |
| Few shot examples                | Providing 2–5 curated examples helps teach structure and tone. System prompting guides note that few shot prompting improves format fidelity, and a few shot store can be part of the prompt architecture.                                                                                                               |
| Tone & Style                     | Sets the voice, style and communication guidelines. System prompts should specify style (e.g., “Be concise; no emojis”). The persona based prompting pattern instructs the model to adopt a specific tone and avoid insults.                                                                                             |
| Safety & Boundaries / Guardrails | Explicit guardrails tell the model what to avoid, such as “never reveal private keys”. Constraints also cover risk boundaries like cost or latency budgets and refusal policies for out of scope requests.                                                                                                               |

### Resources

I want to note that this prompt template was not reached from the first shot, it was influenced by from an n8n tutorial, anyone interested in boosting his prompt is advised to look in the n8n community. Note that on n8n, there are too many great prompts that I did not have enough time to experiment with. As for this template, it was built step by step in parallel with this reference and more additional sections were added based on the result.
[https://www.youtube.com/watch?v=77Z07QnLlB8](https://www.youtube.com/watch?v=77Z07QnLlB8)

## Fastapi integration

To deploy my agent, I built a fastapi application that serves as an interface to the google adk runner. At server startup, I initialize a single, persistent runner instance. This runner is configured with my root agent, an InMemorySessionService to manage conversational state, and an InMemoryMemoryService to provide the agent with long-term memory. By creating this runner only once, I avoid the overhead of re-initializing the agent and its services for every incoming request. However, even though things happened exactly according as stated and directed in the google documentation, I could not figure out why the agent has no memory and wan’t keeping track of the conversation. Hence, this will be further investigated and once I resolve the issue, the solution will be hopefully provided.
Note that I have also tried to stream my outputs following the exact deployment steps found in the reference (google adk streaming) but was not capable to due to a pydantic error that I kept facing. Hence, I just adopted the regular approach without streaming and being organized.
Those issues will be resolved hopefully in the upcoming releases.

### References:

[https://google.github.io/adk-docs/get-started/testing](https://google.github.io/adk-docs/get-started/testing)
[https://google.github.io/adk-docs/streaming/custom-streaming](https://google.github.io/adk-docs/streaming/custom-streaming)
[https://youtu.be/HAJvxR8Hf6w?si=SERc\_ANisOKw1M73](https://youtu.be/HAJvxR8Hf6w?si=SERc_ANisOKw1M73)

