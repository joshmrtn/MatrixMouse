"""
tests/frontend/mock_llm.py

Fake LLM backend for deterministic testing.
Returns predefined responses instead of calling real LLM APIs.
"""

from typing import Callable, Iterator

from matrixmouse.inference.base import LLMBackend, LLMResponse, Tool


class FakeLLMBackend(LLMBackend):
    """
    Fake LLM backend that returns predefined responses.
    
    Usage:
        fake_llm = FakeLLMBackend(["response 1", "response 2", ...])
        # Each call to chat() returns the next response in sequence
    """
    
    def __init__(self, responses: list[str] | None = None):
        """
        Initialize with a list of responses to return.
        
        Args:
            responses: List of response strings. Each call to chat()
                      returns the next response. If exhausted, returns
                      "FAKE RESPONSE" as a fallback.
        """
        self.responses: Iterator[str] = iter(responses or [])
        self.call_count = 0
        self.last_messages: list[dict] = []
    
    def chat(
        self,
        model: str,
        messages: list,
        tools: list[Tool],
        stream: bool = False,
        think: bool = False,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Return the next predefined response."""
        self.call_count += 1
        self.last_messages = messages.copy()
        
        try:
            content = next(self.responses)
        except StopIteration:
            content = f"FAKE RESPONSE (call #{self.call_count})"
        
        # Return a minimal LLMResponse
        return LLMResponse(
            content=content,
            model=model,
            usage={"prompt_tokens": 0, "completion_tokens": len(content.split()), "total_tokens": len(content.split())},
        )
    
    def is_model_available(self, model: str) -> bool:
        """All models are available in the fake backend."""
        return True
    
    def list_models(self) -> list[str]:
        """Return a list of fake model names."""
        return ["fake-model-1", "fake-model-2", "fake-model-3"]
    
    def get_context_length(self, model: str) -> int:
        """Return a fixed context length for all models."""
        return 32768
    
    def ensure_model(self, model: str) -> None:
        """No-op - all models are always available."""
        pass
    
    def reset(self, responses: list[str] | None = None) -> None:
        """Reset the response iterator with new responses."""
        self.responses = iter(responses or [])
        self.call_count = 0
        self.last_messages = []
    
    def get_call_history(self) -> dict:
        """Return the history of all chat() calls for inspection."""
        return {
            "call_count": self.call_count,
            "last_messages": self.last_messages,
        }


class FakeLLMBackendWithErrors(FakeLLMBackend):
    """
    Fake LLM backend that can simulate errors.
    
    Usage:
        fake_llm = FakeLLMBackendWithErrors(
            responses=["ok response"],
            errors=[RuntimeError("API error")]
        )
        # First call raises error, second call returns "ok response"
    """
    
    def __init__(
        self,
        responses: list[str] | None = None,
        errors: list[Exception] | None = None,
    ):
        super().__init__(responses)
        self.errors: Iterator[Exception] = iter(errors or [])
    
    def chat(
        self,
        model: str,
        messages: list,
        tools: list[Tool],
        stream: bool = False,
        think: bool = False,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Raise next error or return next response."""
        self.call_count += 1
        self.last_messages = messages.copy()
        
        # Check for errors first
        try:
            error = next(self.errors)
            raise error
        except StopIteration:
            # No more errors, return response
            return super().chat(
                model, messages, tools, stream, think, chunk_callback
            )
