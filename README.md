# MatrixMouse

Autonomous Python coding agent management system

## What is this?

MatrixMouse learns your repository and tackles any tasks given to it. When completed, the vision is that you could run `matrixmouse run` in your repository root and start giving it tasks to work on right away. 

Designed with local LLMs in mind, with a lot of focus on breaking problems down into small tasks, iterating in small and tightly controlled cycles.

## Status

Early development.

## Installation

### Prerequisites

MatrixMouse is only developed for Linux. You'll need [Docker](https://docs.docker.com/engine/install/), [Docker Compose](https://docs.docker.com/compose/install/linux/#install-using-the-repository), and [Ollama](https://ollama.com/download/linux) installed on the host machine.

### Installation steps

Clone this repository and run the installation script:
```bash
git clone https://github.com/joshmrtn/MatrixMouse.git
cd MatrixMouse
chmod +x install.sh
./install.sh
```

The script will guide you through the rest of the setup.

## Troubleshooting

- Web UI connects and immediately disconnects -> websocket timeout, check nginx `proxy_read_timeout`
- Tests time out -> `test_runner.sh` not running, check `systemctl status matrixmouse-test-runner`
- Agent loops without making progress -> model doesn't support tools or is too small, check `ollama show <model>`



## Notes

### Ollama configuration
Ollama uses an `OLLAMA_MAX_LOADED_MODELS` variable that may cause excessive loading/unloading of models if not adjusted to your system's capabilities. Ideally, you would set this to the number of distinct models you have chosen to use. Recommend setting this value to 4 or more as long as your system can handle it. (By default, it is set to 1 for CPU only systems, and 3 for systems with a GPU).  

Example:

```bash
# start matrixmouse with a maximum of 4 models
OLLAMA_MAX_LOADED_MODELS=4 matrixmouse run
```

You may also set this globally in your shell profile or Ollama's systemd service.

### Testing suite  
`pytest` is assumed, but `unittest` test cases should still work with the agent's tools.
