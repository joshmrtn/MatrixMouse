"""
matrixmouse/loop.py

The inner loop that drives a single agent role for a single task.

Responsibilities:
    - Calling the active model via the injected LLMBackend
    - Catching inference errors and feeding them back as user messages
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
from typing import Any, Callable

from matrixmouse.config import MatrixMouseConfig, MatrixMousePaths, RepoPaths
from matrixmouse.inference.base import LLMBackend, LLMResponse, ToolUseBlock, Tool
from matrixmouse.tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class LoopExitReason(Enum):
    """
    Describes why the agent loop terminated.
    Returned to the orchestrator so it can decide what to do next.
    """
    COMPLETE  = auto()  # agent called declare_complete
    ESCALATE  = auto()  # stuck detector triggered escalation
    DECISION  = auto()  # a tool or turn limit requires a human decision before
                        # the task can continue — orchestrator blocks the task
                        # and emits a decision event; on resume the loop replays
                        # any pending tool calls from the interrupted turn
    ERROR     = auto()  # unrecoverable error
    YIELD     = auto()  # yield control back to orchestrator


@dataclass
class LoopResult:
    """
    The outcome of a single agent loop run.
    Returned to the orchestrator after the loop exits.
    """
    exit_reason:        LoopExitReason
    messages:           list    # full message history at time of exit
    turns_taken:        int
    completion_summary: str  = ""               # populated when exit_reason is COMPLETE
    decision_type:      str  = ""               # populated when exit_reason is DECISION
    decision_payload:   dict = field(default_factory=dict)


class AgentLoop:
    """Drives a single agent role for a single task.

    Instantiated by the orchestrator with a resolved backend, model
    identifier, a starting message history, and references to the
    subsystems it needs. Call run() to start the loop.

    The loop runs until the agent declares completion, the stuck detector
    signals escalation, a human decision is required, the turn limit is
    reached, or a yield signal is received.

    Args:
        backend: Resolved ``LLMBackend`` instance from the router.
        model: Backend-local model identifier to pass to ``backend.chat()``.
        messages: Starting conversation history.
        config: MatrixMouseConfig instance.
        paths: MatrixMousePaths or RepoPaths for this workspace.
        context_manager: Callable ``(messages, config) -> messages``.
        stuck_detector: Callable ``(tool_name, arguments, had_error) -> bool``.
        comms: Callable ``() -> str | None`` — returns pending interjection.
        emit: Callable ``(event_type, data) -> None`` — forwards events to UI.
        persist: Callable ``(messages) -> None`` — persists message history.
        persist_pending: Callable ``(calls) -> None`` — persists pending tool calls.
        wip_commit: Callable ``() -> None`` — WIP commit after each dispatch.
        should_yield: Callable ``() -> bool`` — preemption signal.
        stream: If True, text tokens are forwarded to emit as they arrive.
        think: If True, enable extended thinking on the backend.
        current_repo: Repository name for context, if applicable.
        task_turn_limit: Override for agent_max_turns (0 = use config).
        tools: Role-filtered list of ``Tool`` descriptors passed to the backend.
        allowed_tools: Role-filtered frozenset of tool names for dispatch enforcement.
    """

    def __init__(
        self,
        backend: LLMBackend,
        model: str,
        messages: list,
        config: MatrixMouseConfig,
        paths: MatrixMousePaths | RepoPaths,
        context_manager=None,
        stuck_detector=None,
        comms=None,
        emit=None,
        persist=None,
        persist_pending=None,
        wip_commit=None,
        should_yield=None,
        stream: bool = True,
        think: bool = False,
        current_repo: str | None = None,
        task_turn_limit: int = 0,
        tools: list[Tool] | None = None,
        allowed_tools: frozenset | None = None,
    ):
        self.backend = backend
        self.model = model
        self.messages = list(messages)
        self.config = config
        self.paths = paths
        self._emit = emit or _noop_emit
        self._persist = persist or _noop_persist
        self._persist_pending = persist_pending or _noop_persist_pending
        self._wip_commit = wip_commit or _noop_wip_commit
        self._should_yield = should_yield or _noop_should_yield
        self.stream = stream
        self.think = think
        self.current_repo = current_repo
        self._task_turn_limit = task_turn_limit
        self._tools = tools or []
        self._allowed_tools = allowed_tools

        self._check_context = context_manager or _noop_context_manager
        self._check_stuck = stuck_detector or _noop_stuck_detector
        self._check_interjection = comms or _noop_comms

        self._is_done = False
        self._turns = 0

    def run(self) -> LoopResult:
        """
        Run the agent loop until a terminal condition is reached.

        Returns:
            LoopResult describing why the loop exited and the full message
            history at the time of exit.
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
                    exit_reason=LoopExitReason.DECISION,
                    messages=self.messages,
                    turns_taken=self._turns,
                    decision_type="turn_limit_reached",
                    decision_payload={
                        "turns_taken": self._turns,
                        "turn_limit":  _max,
                    },
                )

            # --- Human interjection check ---
            interjection = self._check_interjection()
            if interjection:
                logger.info("Human interjection received.")
                self.messages.append({
                    "role": "user",
                    "content": (
                        f"[Human operator note — please incorporate before "
                        f"continuing]: {interjection}"
                    ),
                })

            # --- Context window check ---
            self.messages = self._check_context(self.messages, self.config)

            # --- Inference ---
            try:
                response = self._chat_completion()
            except Exception as e:
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
            for block in response.content:
                from matrixmouse.inference.base import ThinkingBlock, TextBlock
                if isinstance(block, ThinkingBlock):
                    logger.debug("Thinking: %s", block.text[:120])
                elif isinstance(block, TextBlock):
                    if self.stream:
                        logger.debug("Content (streamed): %s", block.text[:120])
                    else:
                        logger.info("Content: %s", block.text[:120])

            # --- Append assistant response to history ---
            # Normalise to the standard messages format that all backends
            # accept as conversation history.
            self.messages.append(_response_to_message(response))
            self._persist(self.messages)

            # --- Tool dispatch ---
            tool_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
            if tool_blocks:
                exit_result = self._dispatch_tools(tool_blocks)
                if exit_result is not None:
                    return exit_result
            else:
                logger.debug("No tool calls in turn %d.", self._turns)

            # --- WIP commit ---
            self._wip_commit()

            # --- Yield check ---
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

        return LoopResult(
            exit_reason=LoopExitReason.ERROR,
            messages=self.messages,
            turns_taken=self._turns,
        )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _chat_completion(self) -> LLMResponse:
        """
        Dispatch to the backend, wiring chunk_callback when streaming.

        Returns:
            Fully assembled ``LLMResponse``.
        """
        chunk_callback: Callable[[str], None] | None # type: ignore[assignment]
        if self.stream:
            def chunk_callback(text: str) -> None:
                self._emit("token", {"text": text})
        else:
            chunk_callback = None # type: ignore[assignment]

        return self.backend.chat(
            model=self.model,
            messages=self.messages,
            tools=self._tools,
            stream=self.stream,
            think=self.think,
            chunk_callback=chunk_callback,
        )

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def _dispatch_tools(
        self,
        tool_blocks: list[ToolUseBlock],
        pending_tool_calls: list[dict] | None = None,
    ) -> LoopResult | None:
        """
        Execute each tool call and append results to message history.

        Handles three exit conditions:
            - ``declare_complete``          → COMPLETE
            - ``DecisionRequiredException`` → DECISION
            - stuck detector triggered      → ESCALATE

        A WIP commit is made after each successful dispatch so the workspace
        is always consistent when a task is blocked or context-switched.

        Args:
            tool_blocks: ``ToolUseBlock`` entries from the model response.
                Ignored when ``pending_tool_calls`` is provided.
            pending_tool_calls: Remaining serialised calls to replay, used
                when resuming after a DECISION. ``None`` on a fresh turn.

        Returns:
            ``LoopResult`` if the loop should exit, ``None`` to continue.
        """
        from matrixmouse.tools.task_tools import DecisionRequiredException

        # Build the dispatch queue. On a fresh turn, serialise from blocks.
        # On resume, the caller passes remaining calls directly.
        calls_to_dispatch: list[dict] = list(pending_tool_calls or [
            {"id": b.id, "name": b.name, "arguments": b.input}
            for b in tool_blocks
        ])

        if pending_tool_calls is None and calls_to_dispatch:
            self._persist_pending(calls_to_dispatch)

        while calls_to_dispatch:
            call_dict = calls_to_dispatch[0]
            call_id   = call_dict.get("id", "")
            name      = call_dict["name"]
            arguments = call_dict["arguments"]

            # --- declare_complete is a special exit signal ---
            if name == "declare_complete":
                summary = arguments.get("summary", "")
                logger.info("Agent declared task complete. Summary: %s", summary)
                self._is_done = True
                self._persist_pending([])
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
                logger.warning("Tool '%s' blocked by allowed_tools enforcement.", name)
                self.messages.append(_tool_result_message(call_id, name, result))
                self._persist(self.messages)
                calls_to_dispatch.pop(0)
                self._persist_pending(calls_to_dispatch)
                if self._check_stuck(name, arguments, had_error=True):
                    return LoopResult(
                        exit_reason=LoopExitReason.ESCALATE,
                        messages=self.messages,
                        turns_taken=self._turns,
                    )
                continue

            # --- Normal tool dispatch ---
            had_error = False
            tool = TOOL_REGISTRY.get(name)

            if tool is None:
                result = (
                    f"ERROR: Unknown tool '{name}'. "
                    f"Available tools: {list(TOOL_REGISTRY.keys())}"
                )
                had_error = True
                logger.warning("Unknown tool called: %s", name)
            else:
                try:
                    result = tool.fn(**arguments)
                    logger.info(
                        "Tool: %s(%s) → %s",
                        name, arguments, str(result)[:120],
                    )
                except DecisionRequiredException as exc:
                    logger.info(
                        "Tool '%s' raised DecisionRequiredException: %s",
                        name, exc.decision_type,
                    )
                    self.messages.append(_tool_result_message(
                        call_id, name,
                        f"[Awaiting human approval — decision_type={exc.decision_type}]",
                    ))
                    self._persist(self.messages)
                    # Blocking call stays at front of queue for replay.
                    return LoopResult(
                        exit_reason=LoopExitReason.DECISION,
                        messages=self.messages,
                        turns_taken=self._turns,
                        decision_type=exc.decision_type,
                        decision_payload=exc.payload,
                    )
                except Exception as e:
                    result = f"ERROR calling {name}: {e}"
                    had_error = True
                    logger.warning("Tool %s raised: %s", name, e)

            self.messages.append(_tool_result_message(call_id, name, str(result)))
            self._persist(self.messages)

            calls_to_dispatch.pop(0)
            self._persist_pending(calls_to_dispatch)
            self._wip_commit()

            if self._check_stuck(name, arguments, had_error):
                logger.warning("Stuck detector triggered on tool: %s", name)
                return LoopResult(
                    exit_reason=LoopExitReason.ESCALATE,
                    messages=self.messages,
                    turns_taken=self._turns,
                )

        self._persist_pending([])
        return None


# ---------------------------------------------------------------------------
# Message format helpers
# ---------------------------------------------------------------------------

def _response_to_message(response: LLMResponse) -> dict:
    """
    Normalise an ``LLMResponse`` into a standard assistant message dict.

    Produces a format that all backends accept as conversation history:
    the ``content`` field is a list of typed block dicts matching the
    Anthropic convention, which adapters translate as needed.

    Args:
        response: Assembled ``LLMResponse`` from ``LLMBackend.chat()``.

    Returns:
        Dict with ``role: "assistant"`` and a ``content`` list.
    """
    from matrixmouse.inference.base import TextBlock, ThinkingBlock, ToolUseBlock

    content = []
    for block in response.content:
        if isinstance(block, ThinkingBlock):
            content.append({"type": "thinking", "thinking": block.text})
        elif isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            content.append({
                "type":  "tool_use",
                "id":    block.id,
                "name":  block.name,
                "input": block.input,
            })
    return {"role": "assistant", "content": content}


def _tool_result_message(tool_use_id: str, name: str, result: str) -> dict:
    """
    Build a tool result message to append to conversation history.

    Includes ``tool_use_id`` so backends that require call-result
    correlation (Anthropic, OpenAI) can match the result to its call.

    Args:
        tool_use_id: The ``id`` from the corresponding ``ToolUseBlock``.
        name: Tool name, for logging and Ollama-compat backends.
        result: String result returned by the tool function.

    Returns:
        Dict with ``role: "tool"`` and result payload.
    """
    return {
        "role":        "tool",
        "tool_use_id": tool_use_id,
        "name":        name,
        "content":     result,
    }


# ---------------------------------------------------------------------------
# No-op stubs — replace by injecting real callables from the orchestrator.
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

def _noop_persist_pending(calls: list) -> None:
    """No-op until orchestrator wires in pending_tool_calls persistence."""
    pass
