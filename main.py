import os
import shutil
import logging
from typing import TypedDict, List, Dict, Literal
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel

from sandbox import DockerSandbox

load_dotenv()
init(autoreset=True)
logging.basicConfig(level=logging.INFO)

REPO_NAME = "agentic-generated-repo"
BASE_WORKSPACE = Path(f"./workspaces/{REPO_NAME}")

if BASE_WORKSPACE.exists():
    shutil.rmtree(BASE_WORKSPACE)
BASE_WORKSPACE.mkdir(parents=True)

# -----------------------------------------------------------------------------
# LLM SETUP (Point this to your Qwen Endpoint)
# -----------------------------------------------------------------------------
llm = ChatOpenAI(
    # OpenRouter requires the 'vendor/' prefix
    model="qwen/qwen-2.5-coder-32b-instruct",
    
    # This MUST be set to OpenRouter's URL, or it defaults to OpenAI's
    base_url="https://openrouter.ai/api/v1",
    
    api_key=os.getenv("OPENROUTER_API_KEY"), # Your actual OpenAI key
    temperature=0.1
)

llm_architect = ChatOpenAI(
    model="gpt-4o-mini",  # Smart planner
    api_key=os.getenv("OPENAI_API_KEY"), # Your actual OpenAI key
    temperature=0
)


import ast

def get_defined_symbols(content: str) -> List[str]:
    """
    Parses Python code and returns a list of function/class names defined in it.
    This acts as the 'Source of Truth' for other files.
    """
    try:
        tree = ast.parse(content)
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
        return symbols
    except SyntaxError:
        return []

# -----------------------------------------------------------------------------
# UTILS
# -----------------------------------------------------------------------------
def ensure_requirements(workspace: Path):
    req_path = workspace / "requirements.txt"
    default_reqs = "fastapi\nuvicorn\npydantic\nhttpx\npytest\nrequests\n"
    
    if not req_path.exists():
        with open(req_path, "w") as f: f.write(default_reqs)
        return

    with open(req_path, "r") as f: lines = f.readlines()
    cleaned_lines = []
    forbidden = {"sqlite3", "json", "os", "sys", "re", "math", "random"}
    
    for line in lines:
        pkg_part = line.split("==")[0].split(">=")[0].split("<")[0].strip()
        if pkg_part.lower() in forbidden or not pkg_part:
            continue
        cleaned_lines.append(f"{pkg_part}\n")

    with open(req_path, "w") as f: f.writelines(cleaned_lines)

def get_file_content(workspace: Path, filename: str) -> str:
    path = workspace / filename
    if path.exists():
        with open(path, "r") as f: return f.read()
    return ""

def get_file_tree(workspace: Path) -> str:
    tree = []
    for root, dirs, files in os.walk(workspace):
        level = root.replace(str(workspace), '').count(os.sep)
        indent = ' ' * 4 * (level)
        tree.append(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            tree.append(f"{subindent}{f}")
    return "\n".join(tree)

def clean_code(content: str) -> str:
    """Removes Markdown backticks from LLM output."""
    content = content.strip()
    if content.startswith("```"):
        # Remove first line (e.g. ```python)
        content = "\n".join(content.split("\n")[1:])
    if content.endswith("```"):
        # Remove last line
        content = "\n".join(content.split("\n")[:-1])
    return content
# -----------------------------------------------------------------------------
# STATE
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# NODES
# -----------------------------------------------------------------------------

def architect_node(state: AgentState):
    print(f"{Fore.MAGENTA}👷 ARCHITECT: Designing system structure...{Style.RESET_ALL}")
    
    # Qwen Prompt: Strict, hierarchical, "JSON-First" focus.
    prompt = f"""
    ### ROLE
    You are a Software Architect. You are designing a Python project based on strict requirements.
    
    ### REQUIREMENTS
    {state['requirements']}
    
    ### TASK
    Generate a JSON project plan.
    
    ### ARCHITECTURAL RULES
    1. **Structure**: Use a standard `app/` and `tests/` layout.
    2. **Dependencies**: `app/routes.py` should depend on `app/crud.py` or `app/services.py`.
    3. **Entry Point**: Always include `app/main.py`.
    4. **Config**: Always include `requirements.txt`.
    5. **Init**: Include `__init__.py` files where necessary to make folders packages.
    """
    
    structured_llm = llm_architect.with_structured_output(ProjectPlan)
    plan = structured_llm.invoke([HumanMessage(content=prompt)])
    
    print(f"{Fore.CYAN}Plan: {len(plan.files)} files.{Style.RESET_ALL}")
    return {"plan": plan}

def builder_node(state: AgentState):
    print(f"{Fore.BLUE}🔨 BUILDER: Implementing files...{Style.RESET_ALL}")
    
    plan = state['plan']
    files_created = state['file_contents'].copy()
    sandbox = DockerSandbox(BASE_WORKSPACE)
    is_retry = state['iterations'] > 0

    # --- 1. BUILD THE "SOURCE OF TRUTH" REGISTRY ---
    # We convert the Architect's file list into valid Python module paths.
    # This prevents the "routes" vs "routers" hallucination.
    valid_module_map = {}
    for f in plan.files:
        if f.filename.endswith(".py"):
            # Convert "app/routes.py" -> "app.routes"
            module_path = f.filename.replace("/", ".").replace(".py", "")
            # Handle __init__ edge case ("app/__init__.py" -> "app")
            if module_path.endswith(".__init__"):
                module_path = module_path[:-9] 
            valid_module_map[module_path] = f.filename

    # Create the strict list for the prompt (e.g. "['app.routes', 'app.models']")
    valid_imports_list = list(valid_module_map.keys())
    valid_imports_str = ", ".join(f"'{m}'" for m in valid_imports_list)

    # --- 2. INTELLIGENT SORTING ---
    # Build dependencies first so we can read their symbols.
    def get_priority(filename):
        if "model" in filename: return 1
        if "schema" in filename: return 2
        if "crud" in filename: return 3
        if "service" in filename: return 3
        if "route" in filename: return 4
        if "main" in filename: return 5
        return 6
    
    sorted_files = sorted(plan.files, key=lambda x: get_priority(x.filename))

    # --- 3. HELPER FUNCTIONS ---
    def clean_code(content: str) -> str:
        """Strips Markdown backticks to prevent SyntaxErrors."""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if len(lines) > 1: content = "\n".join(lines[1:])
        if content.endswith("```"):
            lines = content.split("\n")
            if len(lines) > 1: content = "\n".join(lines[:-1])
        return content.strip()

    def smart_get_content(fname):
        if fname in files_created: return files_created[fname]
        return get_file_content(BASE_WORKSPACE, fname)

    # --- 4. EXECUTION LOOP ---
    for spec in sorted_files:
        # Optimization: Don't rebuild static files on retry
        if is_retry and spec.filename in ["README.md", "Dockerfile", ".gitignore", "requirements.txt"]:
            continue

        print(f"   Processing: {spec.filename}...")
        current_content = files_created.get(spec.filename, "")

        # Context Injection (Code from dependencies)
        related_content = ""
        for dep in spec.dependencies:
            content = smart_get_content(dep)
            if content:
                # We strip large files to save tokens, just showing signatures would be better but this works
                related_content += f"\n### DEPENDENCY CODE ({dep}):\n```python\n{content}\n```"
        
        # Test Injection
        if "test" in spec.filename:
            impl_name = spec.filename.replace("tests/test_", "app/").replace("tests/", "app/")
            content = smart_get_content(impl_name)
            if content:
                 related_content += f"\n### TARGET IMPLEMENTATION ({impl_name}):\n```python\n{content}\n```"

        # --- THE PROMPT THAT FIXES THE HALLUCINATION ---
        prompt = f"""
        ### ROLE
        You are a Senior Python Developer.
        
        ### TASK
        Implement the file `{spec.filename}`.
        
        ### PROJECT CONTEXT
        **Requirement:** {state['requirements']}
        **File Description:** {spec.description}
        
        ### 🛡️ STRICT IMPORT REGISTRY (CRITICAL)
        You may **ONLY** import from the following modules. **DO NOT** invent modules that are not on this list.
        
        **VALID MODULES:** [{valid_imports_str}]
        
        **RULES:**
        1. **Check the List:** If you want to import `routers`, LOOK at the list. Does it say `app.routers`? 
           - If NO, but it says `app.routes`, then you **MUST** use `from app.routes import ...`.
        2. **No Hallucinations:** If a module is not in the list, it DOES NOT EXIST.
        3. **Absolute Imports:** Always use absolute imports (e.g., `from app.models import Base`).
        
        {related_content}
        """

        if is_retry:
            prompt += f"""
            
            ### 🚨 FIX MODE
            The previous build failed. Fix `{spec.filename}`.
            
            **ERROR LOGS:**
            {state['test_output'][-2500:]}
            
            **PREVIOUS CODE:**
            ```python
            {current_content}
            ```
            
            **DEBUGGING STRATEGY:**
            1. **ModuleNotFoundError:** This means you imported a name that isn't in the "VALID MODULES" list above. Check the list and correct the import name (e.g., change `routers` to `routes`).
            2. **ImportError:** Check the "DEPENDENCY CODE" block. Did you import a function that doesn't exist? Align your import with the actual function names defined there.
            """

        structured_llm = llm.with_structured_output(CodeFile)
        result = structured_llm.invoke([HumanMessage(content=prompt)])
        
        cleaned_content = clean_code(result.content)
        
        if cleaned_content.strip() != current_content.strip():
             files_created[result.filename] = cleaned_content
             sandbox.write_file(result.filename, cleaned_content)
        
    return {"file_contents": files_created}

def tester_node(state: AgentState):
    print(f"{Fore.YELLOW}🧪 TESTER: Running suite...{Style.RESET_ALL}")
    
    ensure_requirements(BASE_WORKSPACE)
    sandbox = DockerSandbox(BASE_WORKSPACE)
    result = sandbox.run_repo_tests()
    
    if result['exit_code'] == 0:
        print(f"{Fore.GREEN}✅ PASSED!{Style.RESET_ALL}")
        return {"status": "success", "test_output": result['output']}
    else:
        print(f"{Fore.RED}❌ FAILED.{Style.RESET_ALL}")
        print(f"--- LOG START ---\n{result['output'][-1500:]}\n--- LOG END ---")
        return {"status": "failed_check", "test_output": result['output'], "iterations": state['iterations'] + 1}

# -----------------------------------------------------------------------------
# GRAPH
# -----------------------------------------------------------------------------
def should_continue(state: AgentState) -> Literal["builder_node", "done", "failed"]:
    if state['status'] == 'success': return "done"
    if state['iterations'] >= 5: 
        print(f"{Fore.RED}💀 Max retries reached.{Style.RESET_ALL}")
        return "failed"
    print(f"{Fore.RED}↺ Looping back...{Style.RESET_ALL}")
    return "builder_node"

workflow = StateGraph(AgentState)
workflow.add_node("architect_node", architect_node)
workflow.add_node("builder_node", builder_node)
workflow.add_node("tester_node", tester_node)
workflow.set_entry_point("architect_node")
workflow.add_edge("architect_node", "builder_node")
workflow.add_edge("builder_node", "tester_node")
workflow.add_conditional_edges("tester_node", should_continue, {"builder_node": "builder_node", "done": END, "failed": END})

app = workflow.compile()

if __name__ == "__main__":
    USER_REQ = """
    Build a FastAPI service for a library system.
    Features:
    1. Add books (title, author, isbn).
    2. List all books.
    3. Search books by author.
    Include unit tests.
    """
    
    initial_state = {"requirements": USER_REQ, "plan": None, "file_contents": {}, "test_output": "", "iterations": 0, "status": "starting"}
    
    print(f"{Fore.WHITE}🚀 STARTING AGENT...{Style.RESET_ALL}")
    for event in app.stream(initial_state): pass