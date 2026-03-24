"""
matrixmouse/loop.py

The inner loop that drives a single agent role for a single task.

Responsibilities:
    - Calling the active model via Ollama
    - Catching malformed tool call parsing errors at the chat_completion
      level and feeding them back as error messages
    - Executing tool calls and appending results to message history
    - Calling stuck.py after each turn to check for escalation signals
    - Calling context.py before each inference to ensure the context window
      is within bounds
    - Checking comms.py for pending human interjections at the top of each
      iteration
    - Terminating on declare_complete or when the orchestrator signals phase
      transition

Do not add orchestration logic, model selection, or task management here.
Those responsibilities belong to orchestrator.py and router.py respectively.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import ollama

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths
from matrixmouse.tools import TOOLS, TOOL_REGISTRY

logger = logging.getLogger(__name__)


class LoopExitReason(Enum):
    """
    Describes why the agent loop terminated.
    Returned to the orchestrator so it can decide what to do next.
    """
    COMPLETE           = auto() # agent called declare_complete
    ESCALATE           = auto() # stuck detector triggered escalation
    TURN_LIMIT_REACHED = auto() # task turn limit reached, intervention required
    ERROR              = auto() # unrecoverable error
    YIELD              = auto() # yield control back to orchestrator


@dataclass
class LoopResult:
    """
    The outcome of a single agent loop run.
    Returned to the orchestrator after the loop exits.
    """
    exit_reason: LoopExitReason
    messages: list          # full message history at time of exit
    turns_taken: int
    completion_summary: str = ""   # populated when exit_reason is COMPLETE


class AgentLoop:
    """
    Drives a single agent role for a single task.

    Instantiated by the orchestrator with a model, a starting message
    history, and references to the subsystems it needs. Call run() to
    start the loop. The loop runs until the agent declares completion,
    the stuck detector signals escalation, or the turn limit is reached.
    """

    def __init__(
        self,
        model: str,
        messages: list,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths | RepoPaths,
        # These are passed as callables so the loop stays decoupled from
        # the concrete implementations. Stubs can be injected for testing.
        context_manager=None,   # callable: (messages, config) -> messages
        stuck_detector=None,    # callable: (tool_name, arguments, had_error) -> bool
        comms=None,             # callable: () -> str | None
        emit=None,
        persist=None,           # callable: (messages: list) -> None
        wip_commit=None,        # callable: () -> None - WIP commit after dispatch
        should_yield=None,      # callable: () -> bool
        stream: bool = True,    # stream tokens to web UI
        think: bool = False,    # enable extended thinking
        current_repo: str | None = None,
        task_turn_limit: int = 0, # use config.agent_max_turns
        tools: list | None = None,              # role-filtered tool list for models to call
        allowed_tools: frozenset | None = None, # role-filtered tool names for dispatch
    ):
        self.model = model
        self.messages = list(messages)  # defensive copy — don't mutate caller's list
        self.config = config
        self.paths = paths
        self._emit = emit or _noop_emit
        self._persist = persist or _noop_persist
        self._wip_commit = wip_commit or _noop_wip_commit
        self._should_yield = should_yield or _noop_should_yield
        self.stream = stream
        self.think = think
        self.current_repo = current_repo
        self._task_turn_limit = task_turn_limit
        self._tools = tools
        self._allowed_tools = allowed_tools

        # Subsystem callables — fall back to no-ops until implemented
        self._check_context = context_manager or _noop_context_manager
        self._check_stuck = stuck_detector or _noop_stuck_detector
        self._check_interjection = comms or _noop_comms

        self._is_done = False
        self._turns = 0

    def run(self) -> LoopResult:
        """
        Run the agent loop until a terminal condition is reached.

        Returns a LoopResult describing why the loop exited and the
        full message history at the time of exit.
        """
        logger.info("AgentLoop starting. Model: %s", self.model)

        while not self._is_done:

            # --- Safety ceiling ---
            _max = (
                self._task_turn_limit
                if self._task_turn_limit > 0
                else self.config.agent_max_turns
            )
            if self._turns >= _max:
                logger.warning("Turn limit (%d) reached. Exiting loop.", _max)
                return LoopResult(
                    exit_reason=LoopExitReason.TURN_LIMIT_REACHED,
                    messages=self.messages,
                    turns_taken=self._turns,
                )

            # --- Human interjection check ---
            # Checked at the top of every iteration so the agent picks up
            # messages at the next clean loop boundary, never mid-inference.
            interjection = self._check_interjection()
            if interjection:
                logger.info("Human interjection received.")
                self.messages.append({
                    "role": "user",
                    "content": f"[Human operator note — please incorporate before continuing]: {interjection}",
                })

            # --- Context window check ---
            self.messages = self._check_context(self.messages, self.config)

            # --- Inference ---
            try:
                response = self._chat_completion()
            except Exception as e:
                # Ollama failed to parse the model's output (e.g. malformed
                # tool call XML). Feed the error back so the model can retry.
                logger.warning("chat_completion failed: %s", e)
                self.messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response caused a parsing error and no "
                        "tool was executed. Please try again with a valid tool "
                        f"call. Details: {e}"
                    ),
                })
                self._turns += 1
                continue

            self._turns += 1

            # --- Log model output ---
            if response.message.thinking:
                logger.debug("Thinking: %s", response.message.thinking)
            if response.message.content:
                # In streaming mode content was already emitted token by token.
                # Log at debug level only to avoid duplication.
                if self.stream:
                    logger.debug("Content (streamed): %s", response.message.content[:120])
                else:
                    logger.info("Content: %s", response.message.content)

            # --- Append response to history ---
            self.messages.append(response.message)
            self._persist(self.messages)



            # --- Tool dispatch ---
            if response.message.tool_calls:
                exit_result = self._dispatch_tools(response.message.tool_calls)
                if exit_result is not None:
                    return exit_result
            else:
                logger.debug("No tool calls in turn %d.", self._turns)

            # --- WIP commit after every inference dispatch ---
            # Runs after tool dispatch completes so the working tree
            # reflects the full result of this turn before we commit.
            self._wip_commit()

            # --- Yield check (time slice / preemption) ---
            if self._should_yield():
                logger.info(
                    "Yield signal received after turn %d. "
                    "Returning control to scheduler.",
                    self._turns,
                )
                return LoopResult(
                    exit_reason=LoopExitReason.YIELD,
                    messages=self.messages,
                    turns_taken=self._turns,
                )

        # Should not be reachable — loop exits via return inside the while.
        # Included as a safety net.
        return LoopResult(
            exit_reason=LoopExitReason.ERROR,
            messages=self.messages,
            turns_taken=self._turns,
        )


    def _chat_completion(self):
        """
        Dispatch to streaming or batch inference based on self.stream.
        Always returns an object with .message.content, .message.thinking,
        and .message.tool_calls so the caller is unchanged either way.
        """
        if self.stream:
            return self._chat_completion_stream()
        return self._chat_completion_batch()

    def _chat_completion_batch(self):
        """
        Non-streaming inference. Returns the ollama response object directly.
        Used when config disables streaming for this role.
        """
        return ollama.chat(
            model=self.model,
            messages=self.messages,
            stream=False,
            tools=self._tools if self._tools is not None else TOOLS,
            think=self.think,
            keep_alive="2h",
        )

    def _chat_completion_stream(self):
        """
        Streaming inference. Accumulates chunks into a synthetic response
        matching the shape expected by the rest of the loop.

        Content tokens are emitted as 'token' events so the web UI can
        display output in real time. Thinking tokens are accumulated but
        not emitted — they are too verbose for the chat view.

        Tool calls may appear in any chunk and are accumulated via extend.
        Tool dispatch is deferred until the full stream is consumed — never
        dispatch mid-stream.

        Returns a SimpleNamespace with .message matching the ollama Message
        shape: .content, .thinking, .tool_calls.
        """
        from types import SimpleNamespace

        accumulated_content = ""
        accumulated_thinking = ""
        accumulated_tool_calls = []

        stream = ollama.chat(
            model=self.model,
            messages=self.messages,
            stream=True,
            tools=self._tools if self._tools is not None else TOOLS,
            think=self.think,
            keep_alive="2h",
        )

        for chunk in stream:
            msg = chunk.message

            if msg.thinking:
                accumulated_thinking += msg.thinking
                self._emit("thinking", {"text": msg.thinking})

            if msg.content:
                accumulated_content += msg.content
                self._emit("token", {"text": msg.content})

            if msg.tool_calls:
                accumulated_tool_calls.extend(msg.tool_calls)

        # Assemble a synthetic response in the shape the loop expects
        message = SimpleNamespace(
            content=accumulated_content,
            thinking=accumulated_thinking,
            tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
        )
        return SimpleNamespace(message=message)



    def _dispatch_tools(self, tool_calls) -> LoopResult | None:
        """
        Execute each tool call in the response and append results to history.

        Returns a LoopResult if the loop should exit (declare_complete or
        escalation), or None to continue the loop.
        """
        for call in tool_calls:
            name = call.function.name
            arguments = call.function.arguments

            # --- declare_complete is a special exit signal, not a real tool ---
            if name == "declare_complete":
                summary = arguments.get("summary", "")
                logger.info("Agent declared task complete. Summary: %s", summary)
                self._is_done = True
                return LoopResult(
                    exit_reason=LoopExitReason.COMPLETE,
                    messages=self.messages,
                    turns_taken=self._turns,
                    completion_summary=summary,
                )

            # --- Allowlist enforcement ---
            if self._allowed_tools is not None and name not in self._allowed_tools:
                result = (
                    f"ERROR: Tool '{name}' is not permitted for this agent role. "
                    f"Allowed tools: {sorted(self._allowed_tools)}."
                )
                had_error = True
                logger.warning(
                    "Tool '%s' blocked by allowed_tools enforcement.", name
                )
                self.messages.append({
                    "role": "tool",
                    "name": name,
                    "content": result,
                })
                self._persist(self.messages)
                if self._check_stuck(name, arguments, had_error):
                    return LoopResult(
                        exit_reason=LoopExitReason.ESCALATE,
                        messages=self.messages,
                        turns_taken=self._turns,
                    )
                continue


            # --- Normal tool dispatch ---
            had_error = False
            func = TOOL_REGISTRY.get(name)

            if func is None:
                result = f"ERROR: Unknown tool '{name}'. Available tools: {list(TOOL_REGISTRY.keys())}"
                had_error = True
                logger.warning("Unknown tool called: %s", name)
            else:
                try:
                    result = func(**arguments)
                    logger.info("Tool: %s(%s) → %s", name, arguments, str(result)[:120])
                except Exception as e:
                    result = f"ERROR calling {name}: {e}"
                    had_error = True
                    logger.warning("Tool %s raised: %s", name, e)

            self.messages.append({
                "role": "tool",
                "name": name,
                "content": str(result),
            })

            self._persist(self.messages)

            # --- Stuck check after each tool call ---
            if self._check_stuck(name, arguments, had_error):
                logger.warning("Stuck detector triggered on tool: %s", name)
                return LoopResult(
                    exit_reason=LoopExitReason.ESCALATE,
                    messages=self.messages,
                    turns_taken=self._turns,
                )

        return None  # continue the loop


# TODO: replace noop stubs when subsystems are ready.

# ---------------------------------------------------------------------------
# No-op stubs for subsystems not yet implemented.
# These allow the loop to run end-to-end before every dependency exists.
# Replace by passing real callables when the subsystems are ready.
# ---------------------------------------------------------------------------

def _noop_context_manager(messages: list, config: Any) -> list:
    """Passthrough until context.py is implemented."""
    return messages


def _noop_stuck_detector(tool_name: str, arguments: dict, had_error: bool) -> bool:
    """Never escalates until stuck.py is implemented."""
    return False


def _noop_comms() -> None:
    """No interjections until comms.py is implemented."""
    return None

def _noop_emit(event_type: str, data: dict) -> None:
    """No-op emit until comms is wired in."""
    pass

def _noop_persist(messages: list) -> None:
    """No-op until persistence is wired in."""
    pass

def _noop_should_yield() -> bool:
    """Never yields until scheduler is wired in."""
    return False

def _noop_wip_commit() -> None:
    """No-op until git_tools is wired in."""
    pass