"""matrixmouse/inference/fake.py

Fake LLM backend for testing. Returns deterministic, scripted responses
without calling any real LLM provider.

This allows testing the full agent loop, tool calling, and frontend
integration without requiring Ollama, API keys, or network access.

Usage:
    from matrixmouse.inference.fake import FakeBackend
    
    backend = FakeBackend(scripted_responses=[...])
    response = backend.chat(model="fake", messages=[...], tools=[])
"""

from __future__ import annotations

from typing import Callable

from matrixmouse.inference.base import (
    LLMBackend,
    LLMResponse,
    Tool,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ModelNotAvailableError,
    BackendConnectionError,
)


class FakeBackend(LLMBackend):
    """Fake LLM backend for testing.
    
    Supports three modes of operation:
    
    1. **Scripted mode**: Pre-defined responses for each turn
    2. **Echo mode**: Returns the last user message as the response
    3. **Tool-calling mode**: Always requests a specific tool call
    
    All modes are deterministic and require no network access.
    """
    
    def __init__(
        self,
        scripted_responses: list[LLMResponse] | None = None,
        mode: str = "scripted",
        default_tool_call: str | None = None,
    ):
        """
        Args:
            scripted_responses: List of LLMResponse objects to return
                in sequence. When exhausted, falls back to echo mode.
            mode: One of "scripted", "echo", or "tool_call"
            default_tool_call: Tool name to call in tool_call mode
        """
        self._scripted_responses = list(scripted_responses) if scripted_responses else []
        self._response_index = 0
        self._mode = mode
        self._default_tool_call = default_tool_call or "read_file"
        
        # Pre-defined models for testing
        self._models = {
            "fake-coder": 32768,
            "fake-manager": 65536,
            "fake-critic": 32768,
            "fake-writer": 32768,
            "fake-default": 16384,
        }
    
    def chat(
        self,
        model: str,
        messages: list,
        tools: list[Tool],
        stream: bool = False,
        think: bool = False,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Return a scripted or generated fake response."""
        
        if self._mode == "scripted" and self._scripted_responses:
            if self._response_index < len(self._scripted_responses):
                response = self._scripted_responses[self._response_index]
                self._response_index += 1
                return response
            # Fall through to echo mode when scripted responses exhausted
        
        if self._mode == "echo":
            return self._echo_response(messages, tools, think)
        
        if self._mode == "tool_call":
            return self._tool_call_response(tools, self._default_tool_call)
        
        # Default: simple response
        return self._simple_response()
    
    def _echo_response(
        self,
        messages: list,
        tools: list[Tool],
        think: bool,
    ) -> LLMResponse:
        """Echo the last user message back as the response."""
        last_user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_user_message = content
                    break
        
        content = [TextBlock(text=f"I understand: {last_user_message[:200]}")]
        
        if think:
            content.insert(0, ThinkingBlock(text="Processing user request..."))
        
        return LLMResponse(
            content=content,
            input_tokens=len(str(messages)) // 4,
            output_tokens=len(content[0].text) // 4,
            model="fake-default",
            stop_reason="end_turn",
        )
    
    def _tool_call_response(
        self,
        tools: list[Tool],
        tool_name: str,
    ) -> LLMResponse:
        """Return a response that requests a tool call."""
        # Find the tool schema
        tool_schema = None
        for tool in tools:
            if tool.schema["name"] == tool_name:
                tool_schema = tool
                break
        
        # Generate fake arguments based on schema
        fake_args = {}
        if tool_schema and "input_schema" in tool_schema.schema:
            props = tool_schema.schema["input_schema"].get("properties", {})
            for prop_name, prop_def in props.items():
                if prop_def.get("type") == "string":
                    fake_args[prop_name] = f"fake_{prop_name}_value"
                elif prop_def.get("type") == "integer":
                    fake_args[prop_name] = 42
                elif prop_def.get("type") == "boolean":
                    fake_args[prop_name] = True
                elif prop_def.get("type") == "array":
                    fake_args[prop_name] = []
                else:
                    fake_args[prop_name] = "default"
        
        return LLMResponse(
            content=[
                TextBlock(text=f"I'll call {tool_name}..."),
                ToolUseBlock(
                    id=f"fake_tool_call_{id(self)}",
                    name=tool_name,
                    input=fake_args if fake_args else {"path": "/fake/path"},
                ),
            ],
            input_tokens=100,
            output_tokens=50,
            model="fake-default",
            stop_reason="tool_use",
        )
    
    def _simple_response(self) -> LLMResponse:
        """Return a simple text response."""
        # In scripted mode with exhausted responses, fall back to echo-like behavior
        return LLMResponse(
            content=[TextBlock(text="This is a fake LLM response for testing.")],
            input_tokens=50,
            output_tokens=20,
            model="fake-default",
            stop_reason="end_turn",
        )
    
    def is_model_available(self, model: str) -> bool:
        """Check if model is in our fake model list."""
        return model in self._models or model.startswith("fake-")
    
    def list_models(self) -> list[str]:
        """Return list of fake model identifiers."""
        return list(self._models.keys())
    
    def get_context_length(self, model: str) -> int:
        """Return context length for fake models."""
        return self._models.get(model, 16384)
    
    def ensure_model(self, model: str) -> None:
        """No-op for fake models."""
        if not model.startswith("fake-"):
            raise ModelNotAvailableError(f"Fake model '{model}' not available")
    
    def reset(self) -> None:
        """Reset the scripted response index."""
        self._response_index = 0
    
    def set_mode(self, mode: str) -> None:
        """Set the response mode: scripted, echo, or tool_call."""
        self._mode = mode
    
    def add_scripted_response(self, response: LLMResponse) -> None:
        """Add a scripted response to the queue."""
        self._scripted_responses.append(response)
    
    def set_scripted_responses(self, responses: list[LLMResponse]) -> None:
        """Replace the scripted response queue."""
        self._scripted_responses = list(responses)
        self._response_index = 0


# ============================================================================
# Convenience functions for creating common fake responses
# ============================================================================

def fake_text_response(text: str, model: str = "fake-default") -> LLMResponse:
    """Create a fake text-only response."""
    return LLMResponse(
        content=[TextBlock(text=text)],
        input_tokens=len(text) // 4,
        output_tokens=len(text) // 4,
        model=model,
        stop_reason="end_turn",
    )


def fake_tool_call_response(
    tool_name: str,
    tool_args: dict,
    model: str = "fake-default",
) -> LLMResponse:
    """Create a fake tool-call response."""
    import uuid
    return LLMResponse(
        content=[
            ToolUseBlock(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                name=tool_name,
                input=tool_args,
            )
        ],
        input_tokens=50,
        output_tokens=30,
        model=model,
        stop_reason="tool_use",
    )


def fake_thinking_response(
    thinking: str,
    final_text: str,
    model: str = "fake-default",
) -> LLMResponse:
    """Create a fake response with thinking block."""
    return LLMResponse(
        content=[
            ThinkingBlock(text=thinking),
            TextBlock(text=final_text),
        ],
        input_tokens=100,
        output_tokens=80,
        model=model,
        stop_reason="end_turn",
    )
