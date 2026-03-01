# MatrixMouse

Autonomous agent management system

## What is this?

MatrixMouse learns your repository and tackles any tasks given to it. When completed, the vision is that you could run `matrixmouse run` in your repository root and start giving it tasks to work on right away. 

Designed with local LLMs in mind, with a lot of focus on breaking problems down into small tasks, iterating in small and tightly controlled cycles.

## Status

Early development.

## Notes

Ollama uses an `OLLAMA_MAX_LOADED_MODELS` variable that may cause excessive loading/unloading of models if not adjusted to your system's capabilities. Ideally, you would set this to the number of distinct models you have chosen to use. Recommend setting this value to 4 or more as long as your system can handle it. (By default, it is set to 1 for CPU only systems, and 3 for systems with a GPU).  

Example:

```bash
# start matrixmouse with a maximum of 4 models
OLLAMA_MAX_LOADED_MODELS=4 matrixmouse run
```

You may also set this globally in your shell profile or Ollama's systemd service.

