"""tests/inference/test_fake_llm.py

Tests for the fake LLM backend.
"""

import pytest
from matrixmouse.inference.fake import (
    FakeBackend,
    fake_text_response,
    fake_tool_call_response,
    fake_thinking_response,
)
from matrixmouse.inference.base import TextBlock, ThinkingBlock, ToolUseBlock


class TestFakeBackend:
    """Tests for FakeBackend class."""
    
    def test_echo_mode_returns_user_message(self):
        """Echo mode returns the last user message."""
        backend = FakeBackend(mode="echo")
        
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello there!"},
        ]
        
        response = backend.chat(
            model="fake-default",
            messages=messages,
            tools=[],
        )
        
        assert len(response.content) >= 1
        assert isinstance(response.content[0], TextBlock)
        assert "Hello there!" in response.content[0].text
    
    def test_echo_mode_with_thinking(self):
        """Echo mode includes thinking block when enabled."""
        backend = FakeBackend(mode="echo")
        
        messages = [{"role": "user", "content": "Test"}]
        
        response = backend.chat(
            model="fake-default",
            messages=messages,
            tools=[],
            think=True,
        )
        
        assert len(response.content) == 2
        assert isinstance(response.content[0], ThinkingBlock)
        assert isinstance(response.content[1], TextBlock)
    
    def test_tool_call_mode_requests_tool(self):
        """Tool call mode returns a tool use block."""
        backend = FakeBackend(mode="tool_call", default_tool_call="read_file")
        
        tools = [
            type('Tool', (), {
                'schema': {
                    'name': 'read_file',
                    'description': 'Read a file',
                    'input_schema': {
                        'type': 'object',
                        'properties': {
                            'path': {'type': 'string'},
                        },
                        'required': ['path'],
                    },
                }
            })()
        ]
        
        response = backend.chat(
            model="fake-default",
            messages=[{"role": "user", "content": "Read file"}],
            tools=tools,
        )
        
        assert response.stop_reason == "tool_use"
        assert any(isinstance(c, ToolUseBlock) for c in response.content)
    
    def test_scripted_mode_returns_scripted_responses(self):
        """Scripted mode returns pre-defined responses in order."""
        scripted = [
            fake_text_response("First response"),
            fake_text_response("Second response"),
            fake_text_response("Third response"),
        ]
        
        backend = FakeBackend(scripted_responses=scripted, mode="scripted")
        
        # First call returns first response
        response1 = backend.chat(
            model="fake-default",
            messages=[],
            tools=[],
        )
        assert response1.content[0].text == "First response"
        
        # Second call returns second response
        response2 = backend.chat(
            model="fake-default",
            messages=[],
            tools=[],
        )
        assert response2.content[0].text == "Second response"
        
        # Third call returns third response
        response3 = backend.chat(
            model="fake-default",
            messages=[],
            tools=[],
        )
        assert response3.content[0].text == "Third response"
    
    def test_scripted_mode_falls_back_to_simple_response(self):
        """Scripted mode falls back to simple response when responses exhausted."""
        scripted = [fake_text_response("Only response")]
        backend = FakeBackend(scripted_responses=scripted, mode="scripted")
        
        # First call returns scripted response
        response1 = backend.chat(model="fake-default", messages=[
            {"role": "user", "content": "Test"},
        ], tools=[])
        assert response1.content[0].text == "Only response"
        
        # Second call falls back to simple response
        response2 = backend.chat(model="fake-default", messages=[
            {"role": "user", "content": "Echo this"},
        ], tools=[])
        assert response2.content[0].text == "This is a fake LLM response for testing."
    
    def test_reset_resets_scripted_index(self):
        """Reset method resets the scripted response index."""
        scripted = [
            fake_text_response("Response 1"),
            fake_text_response("Response 2"),
        ]
        backend = FakeBackend(scripted_responses=scripted, mode="scripted")
        
        # Consume first response
        backend.chat(model="fake-default", messages=[], tools=[])
        
        # Reset
        backend.reset()
        
        # Should return to first response
        response = backend.chat(model="fake-default", messages=[], tools=[])
        assert response.content[0].text == "Response 1"
    
    def test_is_model_available(self):
        """Test model availability checking."""
        backend = FakeBackend()
        
        assert backend.is_model_available("fake-coder")
        assert backend.is_model_available("fake-manager")
        assert backend.is_model_available("fake-custom")
        assert not backend.is_model_available("ollama:real-model")
    
    def test_list_models(self):
        """Test listing available models."""
        backend = FakeBackend()
        
        models = backend.list_models()
        assert "fake-coder" in models
        assert "fake-manager" in models
        assert "fake-critic" in models
        assert "fake-writer" in models
    
    def test_get_context_length(self):
        """Test context length lookup."""
        backend = FakeBackend()
        
        assert backend.get_context_length("fake-coder") == 32768
        assert backend.get_context_length("fake-manager") == 65536
        assert backend.get_context_length("unknown") == 16384
    
    def test_ensure_model_raises_for_non_fake(self):
        """ensure_model raises for non-fake models."""
        from matrixmouse.inference.base import ModelNotAvailableError
        
        backend = FakeBackend()
        
        with pytest.raises(ModelNotAvailableError):
            backend.ensure_model("ollama:real-model")
    
    def test_ensure_model_noop_for_fake(self):
        """ensure_model is no-op for fake models."""
        backend = FakeBackend()
        
        # Should not raise
        backend.ensure_model("fake-coder")


class TestConvenienceFunctions:
    """Tests for fake response convenience functions."""
    
    def test_fake_text_response(self):
        """Test fake_text_response creates correct response."""
        response = fake_text_response("Hello world", model="fake-test")
        
        assert len(response.content) == 1
        assert isinstance(response.content[0], TextBlock)
        assert response.content[0].text == "Hello world"
        assert response.model == "fake-test"
        assert response.stop_reason == "end_turn"
    
    def test_fake_tool_call_response(self):
        """Test fake_tool_call_response creates correct response."""
        response = fake_tool_call_response(
            tool_name="write_file",
            tool_args={"path": "/test.txt", "content": "test"},
            model="fake-test",
        )
        
        assert response.stop_reason == "tool_use"
        assert len(response.content) == 1
        assert isinstance(response.content[0], ToolUseBlock)
        assert response.content[0].name == "write_file"
        assert response.content[0].input == {"path": "/test.txt", "content": "test"}
    
    def test_fake_thinking_response(self):
        """Test fake_thinking_response creates correct response."""
        response = fake_thinking_response(
            thinking="Let me think about this...",
            final_text="Here's my answer",
            model="fake-test",
        )
        
        assert len(response.content) == 2
        assert isinstance(response.content[0], ThinkingBlock)
        assert response.content[0].text == "Let me think about this..."
        assert isinstance(response.content[1], TextBlock)
        assert response.content[1].text == "Here's my answer"
