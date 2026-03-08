# MatrixMouse

Autonomous Python coding agent management system


## What is this?

MatrixMouse is an autonomous agent management system. It explores your repository and tackles any tasks given to it. 
MatrixMouse runs as a systemd service, manages an agent-owned workspace and local git mirrors, provides a user-level CLI and a web UI for control and visibility, and implements safely scoped and controlled tools for an Ollama powered agent.
Designed with local LLMs in mind, with a lot of focus on breaking problems down into small tasks, iterating in small and tightly controlled cycles.


## Usage

> Note: MatrixMouse is still in early development. CLI commands and API endpoints are subject to change.

The MatrixMouse agent loop runs continuously as a systemd service, acting on tasks if any are assigned. 
Registering a repository creates a clone in the agent's workspace that the agent can interact with. The agent cannot interact with any filesystems outside of its workspace. 
Assigning a task to the agent adds it to the task queue. Tasks can be scoped to particular repositories or can apply to the whole workspace.


### CLI

Register a new repo with MatrixMouse. It clones it into its local workspace, giving the agent access to the repo.
```bash
# Clone a repo from your regular user's workspace
matrixmouse add-repo /home/joshmrtn/repo-name/

# GitHub HTTPS clone link:
matrixmouse add-repo https://github.com/joshmrtn/MatrixMouse.git

# GitHub SSH clone link:
matrixmouse add-repo git@github.com:joshmrtn/MatrixMouse.git
```

Add a task for MatrixMouse to work on interactively:
```bash
matrixmouse tasks add 
```
This prompts you to fill out the details of the task, such as a description and priority level, what repos it is scoped to, etc. The system picks up your task and schedules it by priority. 


### Web UI

The web UI is served at `localhost:8080` by default. It provides:
- Communication channels scoped by workspace or repo
  - Read the agent's currently loaded context, tool calls, and recent actions 
  - Watch thought/content streaming live (for models that support it. Streaming/thinking is toggleable) 
  - View and answer clarification questions, send messages to the agent
- Tasks Tab: View and modify all tasks assigned to MatrixMouse
- Settings Tab: View and modify configuration options. Note: config changes require service restart


## Status

Early development.


## Installation

### Prerequisites

MatrixMouse is only developed for Linux; systemd is required. You'll need [Docker](https://docs.docker.com/engine/install/), [Docker Compose](https://docs.docker.com/compose/install/linux/#install-using-the-repository) (used for sandboxed test execution), and [Ollama](https://ollama.com/download/linux) installed on the host machine.


### Installation steps

Clone this repository and run the installation script:
```bash
git clone https://github.com/joshmrtn/MatrixMouse.git
cd MatrixMouse
chmod +x install.sh
./install.sh
```

The script will guide you through the rest of the setup, which includes:
- Building and installing `matrixmouse` and `matrixmouse-service`
- Creating the matrixmouse system user and `matrixmouse-mirrors` group
- Optional: set up agent credentials (for github SSH and PAT key paths) 
- Optional: set up ntfy for push notifications
- Optional: provides nginx reverse proxy template
- Set some key config defaults

After install, you may need to log out/log in. 


### Quick start

For the system to make use of any GitHub services, it will need an SSH key and PAT (set up at installation time). I **strongly** recommend creating a distinct 'bot' account instead of giving the agent your personal credentials.

MatrixMouse's workspace lives at `/var/lib/matrixmouse-workspace/` by default. Secrets/credentials are stored in `/etc/matrixmouse/secrets/`

```bash
# verify MatrixMouse is running
matrixmouse status

# register your repository
matrixmouse add-repo /home/your_username/your_repo/

# give it a task to work on
matrixmouse tasks add
```
And navigate to the web UI to watch.


### Configuration

MatrixMouse supports a multi-level configuration hierarchy. It loads sane defaults first, then global settings, workspace-wide settings, repo-tracked, then repo-local-untracked. Each level overrides the previous:
1. Field defaults are hardcoded in `matrixmouse.config`
2. Global config: `/etc/matrixmouse/config.toml`
3. Workspace config: `<workspace_root>/.matrixmouse/config.toml`
4. Repo-local-tracked: `<repo_root>/.matrixmouse/config.toml`
5. Repo-local-untracked: `<workspace_root>/.matrixmouse/<repo_name>/config.toml`

Each source overrides the previous. Keys not present in a source are inherited unchanged. 

**Note: Configuration changes will not take effect until the system is restarted.**
```bash
sudo systemctl restart matrixmouse
```

Reading and setting configuration keys is supported through the CLI and through the web UI:


#### CLI Configuration

`get` and `set` config keys using `matrixmouse config get` or `matrixmouse config set`. The `--repo` argument scopes the command to the repo-local config, `--commit` flag writes the config to the repo-local-tracked config.

```bash
# List config keys and their values in the workspace-level config:
matrixmouse config get
```

```bash
# List config keys and their values in a repo-level config
matrixmouse config get --repo my_repo_name
```

> **Example:**    
> To set the workspace coder model to "qwen2.5:4b":
> ```bash
> matrixmouse config set coder_model "qwen2.5:4b"
> ```


#### Web UI Configuration

Navigate to the Settings Tab (button near the bottom-left corner) and select the scope: Workspace or Repo Overrides. 
> **Example:**   
> To change the workspace-wide configuration for `coder_model` to `qwen2.5:4b`, click Settings -> Under Workspace click Models -> enter `qwen2.5:4b` into the Coder Model box.


## Troubleshooting

- Web UI connects and immediately disconnects -> websocket timeout, check nginx `proxy_read_timeout`
- Tests time out -> `test_runner.sh` not running, check `systemctl status matrixmouse-test-runner`
- Agent loops without making progress -> model doesn't support tools or is too small, check `ollama show <model>`


## Notes

### Security Considerations

The API and web UI must be guarded behind a reverse proxy and authentication if you plan to expose it to the open internet. The provided nginx template should be considered the bare minimum. 

Autonomous agents are inherently risky. The current security model is:
- All agent tools that access the filesystem are guarded by a path safety module `matrixmouse/tools/_safety`, which is hard-coded to only allow access to files within the matrixmouse workspace (Default: `/var/lib/matrixmouse-workspace/`)
- All agent tools that run code must run inside a stripped-down container with no network that does not persist between executions. Currently the only tools that allow an agent to execute code are the testing tools `run_tests` and `run_single_test`.


### Current limitations

- Currently the agent can only run python code via pytest in a containerized environment with no network connection for security reasons. It is hardcoded to build a locked-down container calling `pytest` with either a specific test or to run all tests. Future versions should support other testing frameworks, and perhaps other languages.
- Strict SDLC lifecyle phases are enforced, which isn't always appropriate e.g., for a small refactor or bug fix. Future versions should support more flexible task planning and execution.


### Ollama configuration

Ollama uses an `OLLAMA_MAX_LOADED_MODELS` variable that may cause excessive loading/unloading of models if not adjusted to your system's capabilities. Ideally, you would set this to the number of distinct models you have chosen to use. Recommend setting this value to 4 or more as long as your system can handle it. (By default, it is set to 1 for CPU only systems, and 3 for systems with a GPU).  
Example:

```bash
# Override OLLAMA_MAX_LOADED_MODELS for the matrixmouse service
sudo systemctl edit matrixmouse
# Add:
# [Service]
# Environment="OLLAMA_MAX_LOADED_MODELS=4"
```

You may also set this globally in Ollama's systemd service.

## Roadmap

*Roadmap is subject to change, features here are planned but may not make it into the release.*

- [x] Web UI
- [x] Streaming and thinking control per role
- [ ] Flexible task planning
- [ ] Tool scoping per agent role
- [ ] Expanded language support
