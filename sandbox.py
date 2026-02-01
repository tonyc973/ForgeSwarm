import docker
import os
from pathlib import Path

class DockerSandbox:
    def __init__(self, workspace_path: Path):
        self.client = docker.from_env()
        self.image = "python:3.11-slim"
        self.workspace_path = workspace_path.absolute()
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    def run_repo_tests(self) -> dict:
        uid = os.getuid()
        gid = os.getgid()
        
        env = {
            "HOME": "/app",
            "PATH": "/app/.local/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/app:." 
        }

        # FAIL-SAFE COMMAND:
        # 1. Upgrade pip
        # 2. Install requirements.txt (if exists)
        # 3. FORCE install critical libs (pytest, httpx, fastapi) so tests run even if requirements.txt is partial.
        cmd = (
            "bash -c '"
            "pip install --user --upgrade pip > /dev/null 2>&1 && "
            "if [ -f requirements.txt ]; then pip install --user -r requirements.txt; fi && "
            "pip install --user pytest httpx fastapi uvicorn pydantic > /dev/null 2>&1 && "
            "python3 -m pytest -v"
            "'"
        )

        try:
            container = self.client.containers.run(
                self.image,
                command=cmd,
                volumes={str(self.workspace_path): {'bind': '/app', 'mode': 'rw'}},
                working_dir="/app",
                detach=True,
                user=f"{uid}:{gid}",
                environment=env,
                mem_limit="1g",
                network_mode="host", 
            )
            
            result = container.wait()
            logs = container.logs().decode("utf-8")
            container.remove()

            return {
                "exit_code": result['StatusCode'],
                "output": logs
            }
        except Exception as e:
            return {"exit_code": 1, "output": str(e)}

    def write_file(self, filepath: str, content: str):
        full_path = self.workspace_path / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)