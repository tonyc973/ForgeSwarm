import asyncio
import os
import shutil
import logging
from typing import TypedDict, List, Dict, Literal
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from sandbox import DockerSandbox

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini",api_key=os.getenv("OPENAI_API_KEY"), temperature=0.1)

class FileSpec(BaseModel):
    filename: str
    description: str
    dependencies: List[str]

class ProjectPlan(BaseModel):
    files: List[FileSpec]

class AgentState(TypedDict):
    requirements: str
    plan: ProjectPlan
    file_contents: Dict[str, str]
    test_output: str
    iterations: int
    status: str

class CodeFile(BaseModel):
    filename: str
    content: str

requirement = "Build a RESTful API using FastAPI that manages a to-do list with CRUD operations and includes unit tests."

prompt = f"""
    You are a Python Architect.
    Requirement: {requirement}
    
    Output a JSON plan.
    CRITICAL RULES:
    1. Structure: `app/` (code), `tests/` (tests).
    2. Imports: `from app.models import ...` if needed (Absolute imports).
    4. Config: Always Include `requirements.txt` ONLY if needed (if no external libraries, do not include it).
    """
    
structured_llm = llm.with_structured_output(ProjectPlan)
plan = structured_llm.invoke([HumanMessage(content=prompt)])
print(plan)