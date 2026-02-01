import git
from pathlib import Path
from colorama import Fore, Style

class GitManager:
    def __init__(self, workspace_path: Path, remote_url: str):
        self.path = workspace_path
        self.remote_url = remote_url
        self.repo = None

    def setup_repo(self):
        """Init repo or attach to existing one."""
        if (self.path / ".git").exists():
            self.repo = git.Repo(self.path)
        else:
            print(f"{Fore.YELLOW}Initializing new Git repo...{Style.RESET_ALL}")
            self.repo = git.Repo.init(self.path)
            # Check if remote exists, if not add it
            try:
                self.repo.create_remote('origin', self.remote_url)
            except git.exc.GitCommandError:
                pass # Remote might already exist

    def create_branch(self, branch_name: str):
        self.setup_repo()
        # Checkout new branch
        current = self.repo.create_head(branch_name)
        current.checkout()
        print(f"{Fore.GREEN}Checked out branch: {branch_name}{Style.RESET_ALL}")

    def commit_and_push(self, message: str):
        if not self.repo: return False
        
        try:
            self.repo.git.add(A=True)
            self.repo.index.commit(message)
            print(f"{Fore.GREEN}Changes committed.{Style.RESET_ALL}")
            
            # Assumes SSH keys are set up on the server
            origin = self.repo.remote(name='origin')
            origin.push(refspec=f'{self.repo.active_branch}:{self.repo.active_branch}')
            print(f"{Fore.GREEN}🚀 PUSH SUCCESSFUL!{Style.RESET_ALL}")
            return True
        except Exception as e:
            print(f"{Fore.RED}Git Push Failed: {e}{Style.RESET_ALL}")
            return False
