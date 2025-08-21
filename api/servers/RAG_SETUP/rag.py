# from langchain.tools import BaseTool
# from pydantic import BaseModel, Field
# from typing import Optional, Type, Annotated
# import os
# from pathlib import Path
# from langchain_community.document_loaders import DirectoryLoader, PyMuPDFLoader
# import re
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain.embeddings.openai import OpenAIEmbeddings
# from langchain_openai import ChatOpenAI
# from langchain.vectorstores import Chroma
# from langchain.llms import OpenAI
# from langchain.retrievers.self_query.base import SelfQueryRetriever
# from langchain.chains.query_constructor.base import AttributeInfo
# from langchain.chains import  ConversationalRetrievalChain
# from typing import Sequence, Union
# from langchain_core.language_models import BaseLanguageModel
# from langchain_core.vectorstores import VectorStore
# from langchain.chains.conversational_retrieval.base import BaseConversationalRetrievalChain
# from typing import List  # needed for lectures: Optional[List[int]]
# import shutil           # used when forcing rebuild on course change
# from langchain_openai import OpenAIEmbeddings


# def educated_retriever(llm: BaseLanguageModel,
#                        metadata_field_info: Sequence[Union[AttributeInfo, dict]],
#                        document_content: str,
#                        vectordb: VectorStore,
#                        chain_type: str ="stuff") -> BaseConversationalRetrievalChain:
#     """_summary_
#     Builds a conversational retrieval QA pipeline by combining a SelfQueryRetriever (LLM-guided vector search + structured metadata filters) with a ConversationalRetrievalChain. 
#     Given metadata field descriptions and a natural-language summary of the document contents, it lets the agent translate user questions into filtered vector store queries, handle follow-ups using chat history, and return answers with cited source documents.

#     Inputs:
#     - llm (BaseLanguageModel): LLM used to infer filters and generate answers.
#     - metadata_field_info (Sequence[Union[AttributeInfo, dict]]): Descriptions of filterable metadata fields (name/type/description/constraints).
#     - document_content (str): Plain-language description of what each document represents.
#     - vectordb (VectorStore): Backing vector store containing embedded documents.
#     - chain_type (str, optional): QA chain type (e.g., "stuff", "map_reduce", "refine", "map_rerank"). Default: "map reduce".

#     Return type:
#     - BaseConversationalRetrievalChain — a callable chain expecting {"question": str, "chat_history": list[tuple[str, str]]}
#     and returning {"answer": str, "source_documents": List[Document], ...}.
#     """

#     retriever = SelfQueryRetriever.from_llm(
#         llm,
#         vectordb,
#         document_contents=document_content,
#         metadata_field_info=metadata_field_info,
#         verbose=True)
#     qa = ConversationalRetrievalChain.from_llm(
#     llm=llm,
#     retriever=retriever,
#     chain_type=chain_type, # depending on the state, might be refine (mostprobably)
#     return_source_documents=True,
#     )
#     return qa


# from langchain.tools import BaseTool
# from pydantic import BaseModel, Field
# from typing import Optional, Type, Annotated
# import threading

# class RAGSearchInput(BaseModel):
#     """Input schema for the RAG search tool"""
#     query: str = Field(..., description="The query to search for in the course materials")
#     course_path: Optional[str] = Field(default=None, description="Path to the course materials")
#     chain_type: Optional[str] = Field(default="stuff", description="Chain type for the QA system")

# class RAGSearchTool(BaseTool):
#     name: Annotated[str, Field(description="Name of the tool")] = "educated_course_material_search"
#     description: Annotated[str, Field(description="Description of the tool")] = """
#     Search through course materials using an educated RAG approach.
#     Uses metadata filtering and conversational capabilities to provide relevant information.
#     """
#     args_schema: Type[BaseModel] = RAGSearchInput
#     default_course_path: Path = Field(
#         default_factory=lambda: Path("../../Courses/signals and systems")
#     )
#     persist_directory: Path = Field(
#         default_factory=lambda: Path("../docs/chroma")
#     )
#     collection_name: str = "course_materials"

#     # # --- RUNTIME (non-serialized) PRIVATE ATTRS ---
#     # _qa_chain: Any = PrivateAttr(default=None)
#     # _metadata_field_info: Any = PrivateAttr(default=None)
#     # _vectordb: Any = PrivateAttr(default=None)
#     # _embeddings: Any = PrivateAttr(default=None)
#     # _init_lock: Any = PrivateAttr(default_factory=threading.Lock)


#     def __init__(
#         self,
#         default_course_path: Optional[Path] = None,
#         persist_directory: Optional[Path] = None,
#         collection_name: str = "course_materials",
#     ):
#         super().__init__()
#         base_dir = Path(__file__).resolve().parent.parent.parent
#         self.default_course_path = default_course_path or base_dir / "Courses" / "signals and systems"
#         self.persist_directory = Path(persist_directory or "../../Rag/docs/chroma").resolve()
#         self.collection_name = collection_name

#         self._qa_chain = None
#         self._metadata_field_info = None
#         self._vectordb = None
#         self._embeddings = OpenAIEmbeddings()
#         self._init_lock = threading.Lock()  # guard against concurrent init

#     # -i added this method for the sake of optimality by my self
#     def _load_or_build_vectordb(self):
#         db_file=self.persist_directory/"chroma.sqlite3"
#         if db_file.exists():
#             self._vectordb=Chroma(
#                 persist_directory=str(self.persist_directory),
#                 collection_name=self.collection_name,
#                 embedding_function=self._embeddings,
#             )
#             return

#         # Slow path: build from PDFs, then persist
#         loader = DirectoryLoader(
#             str(self.default_course_path),
#             glob="**/*.pdf",
#             loader_cls=PyMuPDFLoader,
#         )
#         raw_docs = loader.load()

#         # ... (your existing metadata processing block unchanged) ...

#         splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=250)
#         split_docs = splitter.split_documents(raw_docs)

#         self.persist_directory.mkdir(parents=True, exist_ok=True)
#         self._vectordb = Chroma.from_documents(
#             documents=split_docs,
#             embedding=self._embeddings,
#             collection_name=self.collection_name,
#             persist_directory=str(self.persist_directory),
#         )
#     def _run(
#         self,
#         query: str,
#         course_path: Optional[str] = None,
#         chain_type: Optional[str] = None,          # kept for compatibility; ignored unless you want to rebuild
#         category: Optional[str] = None,
#         chapter: Optional[int] = None,
#         lecture_number: Optional[int] = None,
#         lectures: Optional[List[int]] = None,
#         lecture_min: Optional[int] = None,
#         lecture_max: Optional[int] = None,
#         k: int = 5,
#     ) -> str:
#         """Execute the RAG search (optionally constrained by metadata filters)."""

#         # Allow switching course on the fly
#         if course_path:
#             self.default_course_path = Path(course_path)
#             self._qa_chain = None  # Force re-init for new corpus

#         # Make sure components exist
#         self._initialize_components()

#         # Build a HARD filter (ANDed with SQR’s inferred filter)
#         # Keep it Chroma-friendly: primitives + {$lte,$gte} for ranges
#         flt = {}
#         if category:
#             flt["category"] = category
#         if chapter is not None:
#             flt["chapter"] = chapter
#         # If a single lecture number is requested, match exact or within [lecture_min, lecture_max]
#         if lecture_number is not None:
#             # Use an $or across exact number OR range gate (Chroma supports $and/$or/$lte/$gte)
#             lecture_gate = {
#                 "$or": [
#                     {"lecture_number": lecture_number},
#                     {"$and": [
#                         {"lecture_min": {"$lte": lecture_number}},
#                         {"lecture_max": {"$gte": lecture_number}},
#                     ]}
#                 ]
#             }
#             # Merge $or with any existing filter via $and (if needed)
#             if flt:
#                 flt = {"$and": [flt, lecture_gate]}
#             else:
#                 flt = lecture_gate

#         # Stash current search kwargs, then apply ours temporarily
#         retr = self._qa_chain.retriever
#         orig_kwargs = dict(getattr(retr, "search_kwargs", {}) or {})
#         try:
#             new_kwargs = {"k": k}
#             if flt:
#                 new_kwargs["filter"] = flt
#             # Update (temporary)
#             retr.search_kwargs.update(new_kwargs)

#             # Run QA
#             response = self._qa_chain({"question": query, "chat_history": []})

#             # Format response
#             answer = (response.get("answer") or "").strip()
#             sources = []
#             for i, doc in enumerate(response.get("source_documents", []) or [], 1):
#                 md = doc.metadata or {}
#                 parts = [f"[{i}] {md.get('category', 'unknown')}"]
#                 if md.get("chapter") is not None:
#                     parts.append(f"Chapter {md.get('chapter')}")
#                 if md.get("lecture_number") is not None:
#                     parts.append(f"Lecture {md.get('lecture_number')}")
#                 else:
#                     # show range if present
#                     lmin, lmax = md.get("lecture_min"), md.get("lecture_max")
#                     if isinstance(lmin, int) or isinstance(lmax, int):
#                         parts.append(f"Lectures {lmin}–{lmax}")
#                 page = md.get("page") or md.get("page_or_slide")
#                 if page is not None:
#                     parts.append(f"p.{page}")
#                 parts.append(md.get("filename", "unknown file"))
#                 sources.append(" | ".join(parts))

#             return (
#                 f"Answer: {answer}\n\n"
#                 "Sources:\n" + ("\n".join(sources) if sources else "(none)")
#             )

#         except Exception as e:
#             return f"Error: {e!r}"
#         finally:
#             # Always restore retriever kwargs so filters don't leak across tool calls
#             retr.search_kwargs.clear()
#             retr.search_kwargs.update(orig_kwargs)


import re
import shutil
import threading
from pathlib import Path
from typing import Any, List, Optional, Sequence, Type, Union, Annotated

from langchain.chains import ConversationalRetrievalChain
from langchain.chains.conversational_retrieval.base import BaseConversationalRetrievalChain
from langchain.chains.query_constructor.base import AttributeInfo
from pydantic import BaseModel, Field 
from langchain_community.document_loaders import DirectoryLoader, PyMuPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_core.language_models import BaseLanguageModel
from langchain_core.vectorstores import VectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain.tools import BaseTool


def educated_retriever(
    llm: BaseLanguageModel,
    metadata_field_info: Sequence[Union[AttributeInfo, dict]],
    document_content: str,
    vectordb: VectorStore,
    chain_type: str = "stuff",
) -> BaseConversationalRetrievalChain:
    """
    Builds a conversational retrieval QA pipeline by combining a SelfQueryRetriever
    with a ConversationalRetrievalChain.
    """
    retriever = SelfQueryRetriever.from_llm(
        llm,
        vectordb,
        document_contents=document_content,
        metadata_field_info=metadata_field_info,
        verbose=True,
    )
    qa = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        chain_type=chain_type,
        return_source_documents=True,
    )
    return qa


class RAGSearchInput(BaseModel):
    """Input schema for the RAG search tool"""
    query: str = Field(..., description="The query to search for in the course materials")
    course_path: Optional[str] = Field(default=None, description="Path to the course materials")
    chain_type: Optional[str] = Field(default="stuff", description="Chain type for the QA system")


class RAGSearchTool(BaseTool):
    name: Annotated[str, Field(description="Name of the tool")] = "educated_course_material_search"
    description: Annotated[str, Field(description="Description of the tool")] = """
    Search through course materials using an educated RAG approach.
    Uses metadata filtering and conversational capabilities to provide relevant information.
    """
    args_schema: Type[BaseModel] = RAGSearchInput
    default_course_path: Path
    persist_directory: Path
    collection_name: str = "ele430_signals"

    _qa_chain: Any = None
    _vectordb: Any = None
    _embeddings: Any = None
    _init_lock: Any = None

    def __init__(
        self,
        default_course_path: Optional[Path] = None,
        persist_directory: Optional[Path] = None,
        collection_name: str = "ele430_signals",
    ):
        # First, determine the final paths for the required fields.
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        final_course_path = default_course_path or base_dir / "Courses" / "signals and systems"
        final_persist_dir = Path(persist_directory or base_dir / "Rag/docs/chroma").resolve()
        # Now, call super().__init__() and pass the required fields as keyword arguments.
        super().__init__(
            default_course_path=final_course_path,
            persist_directory=final_persist_dir,
            collection_name=collection_name
        )

        # Initialize the non-Pydantic, private attributes.
        self._embeddings = OpenAIEmbeddings()
        self._init_lock = threading.Lock()

    def _load_or_build_vectordb(self):
        db_file = self.persist_directory / "chroma.sqlite3"
        if db_file.exists() and self._vectordb is None:
            self._vectordb = Chroma(
                persist_directory=str(self.persist_directory),
                collection_name=self.collection_name,
                embedding_function=self._embeddings,
            )
            return

        if self._vectordb is not None:
            return

        # Slow path: build from PDFs, then persist
        loader = DirectoryLoader(
            str(self.default_course_path),
            glob="**/*.pdf",
            loader_cls=PyMuPDFLoader,
        )
        raw_docs = loader.load()

        # Metadata processing logic
        for d in raw_docs:
            p = Path(d.metadata["source"])
            parts_lower = [x.lower() for x in p.parts]
            parts_joined = "/".join(parts_lower)
            metadata = {
                "category": "other", "chapter": None, "lecture_number": None,
                "lecture_min": None, "lecture_max": None, "has_multiple_lectures": False,
                "assignment_number": None, "is_solution": False, "exam_number": None,
                "term_year": None,
            }
            if "chapters" in parts_lower:
                metadata["category"] = "chapters"
                m = re.search(r"chapter\s*(\d+)", p.parent.name, re.I)
                metadata["chapter"] = int(m.group(1)) if m else None
                lec_nums = sorted({int(n) for n in re.findall(r"[ _-]lecture\s*(\d+)", p.name, re.I)})
                if lec_nums:
                    metadata["has_multiple_lectures"] = len(lec_nums) > 1
                    if len(lec_nums) == 1: metadata["lecture_number"] = lec_nums[0]
                    metadata["lecture_min"], metadata["lecture_max"] = min(lec_nums), max(lec_nums)
            elif "syllabus" in parts_lower:
                metadata["category"] = "syllabus"
            elif "assignments" in parts_joined:
                metadata["category"] = "assignments_solutions" if "solutions" in parts_joined else "assignments"
                metadata["is_solution"] = "solutions" in parts_joined
                m = re.search(r"assignment\s*(\d+)", p.stem, re.I)
                metadata["assignment_number"] = int(m.group(1)) if m else None
            elif "previouses" in parts_lower or "exams" in parts_lower:
                metadata["category"] = "exams"
                m = re.search(r"exam\s*(\d+)", p.name, re.I)
                metadata["exam_number"] = int(m.group(1)) if m else None
                m_term = re.search(r"(spring|summer|fall|autumn|winter)[ _-]?(\d{4})", p.stem, re.I)
                if m_term: metadata["term_year"] = int(m_term.group(2))
                metadata["is_solution"] = bool(re.search(r"solution", p.stem, re.I))
            
            d.metadata.update(metadata)
            d.metadata.update({
                "doc_id": p.stem, "filename": p.name, "relpath": str(p.relative_to(self.default_course_path))
            })

        splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=250)
        split_docs = splitter.split_documents(raw_docs)

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._vectordb = Chroma.from_documents(
            documents=split_docs,
            embedding=self._embeddings,
            collection_name=self.collection_name,
            persist_directory=str(self.persist_directory),
        )

    def _initialize_components(self):
        """Initialize the RAG components if not already initialized."""
        if self._qa_chain is not None:
            return
        with self._init_lock:
            if self._qa_chain is not None:
                return
            self._load_or_build_vectordb()
            metadata_field_info = [
                AttributeInfo(name="category", type="string", description="Type of document: chapters | syllabus | assignments | assignments_solutions | exams | other"),
                AttributeInfo(name="chapter", type="integer", description="Chapter number"),
                AttributeInfo(name="lecture_number", type="integer", description="Specific lecture number"),
                AttributeInfo(name="lecture_min", type="integer", description="First lecture number in a range"),
                AttributeInfo(name="lecture_max", type="integer", description="Last lecture number in a range"),
                AttributeInfo(name="assignment_number", type="integer", description="Assignment number"),
                AttributeInfo(name="is_solution", type="boolean", description="Whether document is a solution"),
                AttributeInfo(name="exam_number", type="integer", description="Exam number"),
                AttributeInfo(name="term_year", type="integer", description="Academic year for an exam"),
            ]
            llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")
            self._qa_chain = educated_retriever(
                llm=llm,
                metadata_field_info=metadata_field_info,
                document_content="Course materials for Signals and Systems",
                vectordb=self._vectordb,
                chain_type="stuff",
            )

    def _run(
        self,
        query: str,
        course_path: Optional[str] = None,
        category: Optional[str] = None,
        chapter: Optional[int] = None,
        lectures: Optional[List[int]] = None,
        k: int = 10,
    ) -> str:
        """
        Executes the RAG search by enriching the user query with hard filters
        and letting the SelfQueryRetriever generate the final vector store query.
        """
        if course_path:
            new_path = Path(course_path)
            if self.default_course_path != new_path:
                self.default_course_path = new_path
                self._qa_chain = None
                self._vectordb = None
                if self.persist_directory.exists():
                    shutil.rmtree(self.persist_directory)

        self._initialize_components()

        query_parts = [query]
        if category:
            query_parts.append(f"from the {category} category")
        if chapter is not None:
            query_parts.append(f"from chapter {chapter}")
        if lectures:
            lec_str = ", ".join(map(str, lectures))
            query_parts.append(f"from lecture(s) {lec_str}")
        
        enriched_query = " ".join(query_parts)

        retr = self._qa_chain.retriever
        orig_kwargs = retr.search_kwargs.copy()
        try:
            retr.search_kwargs["k"] = k
            response = self._qa_chain({"question": enriched_query, "chat_history": []})

            answer = (response.get("answer") or "").strip()
            sources = []
            for i, doc in enumerate(response.get("source_documents", []) or [], 1):
                md = doc.metadata or {}
                parts = [f"[{i}] {md.get('category', 'unknown')}"]
                if md.get("chapter") is not None:
                    parts.append(f"Ch. {md.get('chapter')}")
                if md.get("lecture_number") is not None:
                    parts.append(f"Lec. {md.get('lecture_number')}")
                elif md.get("lecture_min") is not None:
                    parts.append(f"Lecs. {md.get('lecture_min')}–{md.get('lecture_max')}")
                page = md.get("page")
                if page is not None:
                    parts.append(f"p.{page+1}")
                parts.append(md.get("filename", "unknown file"))
                sources.append(" | ".join(parts))

            return f"Answer: {answer}\n\nSources:\n" + ("\n".join(sources) if sources else "(none)")
        except Exception as e:
            return f"Error: {e!r}"
        finally:
            if self._qa_chain:
                self._qa_chain.retriever.search_kwargs = orig_kwargs