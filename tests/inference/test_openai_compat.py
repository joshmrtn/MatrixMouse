"""
tests/inference/test_openai_compat.py

Unit tests for openai_compat.py helper functions.

Tests:
    - to_openai_messages passes through system messages unchanged
    - to_openai_messages passes through user messages unchanged
    - to_openai_messages converts assistant content blocks to tool_calls
    - to_openai_messages serialises tool input as JSON string
    - to_openai_messages drops ThinkingBlock
    - to_openai_messages handles plain string assistant content
    - to_openai_messages translates tool_use_id → tool_call_id
    - finalise_tool_calls parses JSON string arguments
    - finalise_tool_calls handles already-parsed dict arguments
    - finalise_tool_calls generates fallback ID when id is empty
    - finalise_tool_calls returns empty list for empty input
    - finalise_tool_calls orders by index
"""

import json

from matrixmouse.inference.openai_compat import to_openai_messages, finalise_tool_calls


# ---------------------------------------------------------------------------
# to_openai_messages tests
# ---------------------------------------------------------------------------


class TestToOpenaiMessages:
    """Tests for to_openai_messages function."""

    def test_passes_through_system_messages_unchanged(self):
        """to_openai_messages passes through system messages unchanged."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_passes_through_user_messages_unchanged(self):
        """to_openai_messages passes through user messages unchanged."""
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_passes_through_multiple_user_messages_unchanged(self):
        """Multiple user messages pass through unchanged."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "How are you?"},
        ]
        result = to_openai_messages(messages)
        assert result == messages

    def test_converts_assistant_content_blocks_to_tool_calls(self):
        """to_openai_messages converts assistant content blocks to tool_calls."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_abc123",
                        "name": "read_file",
                        "input": {"path": "/path/to/file.txt"},
                    }
                ],
            }
        ]
        result = to_openai_messages(messages)
        
        assert len(result) == 1
        assert "tool_calls" in result[0]
        assert len(result[0]["tool_calls"]) == 1
        tool_call = result[0]["tool_calls"][0]
        assert tool_call["id"] == "call_abc123"
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "read_file"

    def test_serialises_tool_input_as_json_string(self):
        """to_openai_messages serialises tool input as JSON string."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_abc",
                        "name": "test_tool",
                        "input": {"x": 42, "y": "hello"},
                    }
                ],
            }
        ]
        result = to_openai_messages(messages)
        
        tool_call = result[0]["tool_calls"][0]
        arguments = tool_call["function"]["arguments"]
        # Should be a JSON string, not a dict
        assert isinstance(arguments, str)
        assert json.loads(arguments) == {"x": 42, "y": "hello"}

    def test_drops_thinking_block(self):
        """to_openai_messages drops ThinkingBlock."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "Here's the answer."},
                ],
            }
        ]
        result = to_openai_messages(messages)
        
        # Thinking block should be dropped
        assert result[0]["content"] == "Here's the answer."
        assert "thinking" not in str(result)

    def test_drops_thinking_block_before_tool_calls(self):
        """Thinking blocks before tool calls are dropped."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Hmm..."},
                    {"type": "tool_use", "id": "call_1", "name": "tool", "input": {}},
                ],
            }
        ]
        result = to_openai_messages(messages)
        
        assert len(result[0]["tool_calls"]) == 1
        assert "thinking" not in str(result)

    def test_handles_plain_string_assistant_content(self):
        """to_openai_messages handles plain string assistant content."""
        messages = [
            {"role": "assistant", "content": "Hello, how can I help you?"},
        ]
        result = to_openai_messages(messages)
        
        assert result == messages

    def test_handles_mixed_text_and_tool_blocks(self):
        """Mixed text and tool blocks are handled correctly."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read that file."},
                    {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "test.txt"}},
                    {"type": "text", "text": "Done reading."},
                ],
            }
        ]
        result = to_openai_messages(messages)
        
        assert result[0]["content"] == "Let me read that file. Done reading."
        assert len(result[0]["tool_calls"]) == 1

    def test_translates_tool_use_id_to_tool_call_id(self):
        """to_openai_messages translates tool_use_id → tool_call_id."""
        messages = [
            {
                "role": "tool",
                "tool_use_id": "call_abc123",
                "name": "read_file",
                "content": "File contents here",
            }
        ]
        result = to_openai_messages(messages)
        
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_abc123"
        assert "tool_use_id" not in result[0]

    def test_handles_tool_message_with_tool_call_id_already(self):
        """Tool messages with tool_call_id already are handled."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "name": "read_file",
                "content": "File contents",
            }
        ]
        result = to_openai_messages(messages)
        
        assert result[0]["tool_call_id"] == "call_abc123"

    def test_handles_empty_tool_message(self):
        """Empty tool message fields are handled gracefully."""
        messages = [
            {"role": "tool"}
        ]
        result = to_openai_messages(messages)
        
        assert result[0]["tool_call_id"] == ""
        assert result[0]["name"] == ""
        assert result[0]["content"] == ""

    def test_handles_conversation_with_multiple_roles(self):
        """Full conversation with multiple roles is handled correctly."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hi there!"},
                    {"type": "tool_use", "id": "call_1", "name": "tool", "input": {}},
                ],
            },
            {
                "role": "tool",
                "tool_use_id": "call_1",
                "name": "tool",
                "content": "Result",
            },
            {"role": "user", "content": "Thanks"},
        ]
        result = to_openai_messages(messages)
        
        assert len(result) == 5
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert "tool_calls" in result[2]
        assert result[3]["role"] == "tool"
        assert result[3]["tool_call_id"] == "call_1"
        assert result[4]["role"] == "user"


# ---------------------------------------------------------------------------
# finalise_tool_calls tests
# ---------------------------------------------------------------------------


class TestFinaliseToolCalls:
    """Tests for finalise_tool_calls function."""

    def test_parses_json_string_arguments(self):
        """finalise_tool_calls parses JSON string arguments."""
        raw = {
            0: {
                "id": "call_abc123",
                "name": "read_file",
                "arguments": '{"path": "/path/to/file.txt"}',
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["id"] == "call_abc123"
        assert result[0]["name"] == "read_file"
        assert result[0]["input"] == {"path": "/path/to/file.txt"}

    def test_handles_already_parsed_dict_arguments(self):
        """finalise_tool_calls handles already-parsed dict arguments."""
        raw = {
            0: {
                "id": "call_abc123",
                "name": "read_file",
                "arguments": {"path": "/path/to/file.txt"},
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["input"] == {"path": "/path/to/file.txt"}

    def test_generates_fallback_id_when_id_is_empty(self):
        """finalise_tool_calls generates fallback ID when id is empty."""
        raw = {
            0: {
                "id": "",
                "name": "test_tool",
                "arguments": "{}",
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["id"].startswith("call_")
        # ID format is "call_{uuid.hex[:8]}" = 5 + 8 = 13 chars
        assert len(result[0]["id"]) == 13

    def test_returns_empty_list_for_empty_input(self):
        """finalise_tool_calls returns empty list for empty input."""
        result = finalise_tool_calls({})
        assert result == []

    def test_orders_by_index(self):
        """finalise_tool_calls orders by index."""
        raw = {
            2: {"id": "call_2", "name": "tool2", "arguments": "{}"},
            0: {"id": "call_0", "name": "tool0", "arguments": "{}"},
            1: {"id": "call_1", "name": "tool1", "arguments": "{}"},
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 3
        assert result[0]["id"] == "call_0"
        assert result[1]["id"] == "call_1"
        assert result[2]["id"] == "call_2"

    def test_handles_invalid_json_gracefully(self):
        """finalise_tool_calls handles invalid JSON gracefully."""
        raw = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
                "arguments": "not valid json{",
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["input"] == {}

    def test_handles_empty_arguments(self):
        """finalise_tool_calls handles empty arguments string."""
        raw = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
                "arguments": "",
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["input"] == {}

    def test_handles_missing_arguments_key(self):
        """finalise_tool_calls handles missing arguments key."""
        raw = {
            0: {
                "id": "call_abc",
                "name": "test_tool",
            }
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 1
        assert result[0]["input"] == {}

    def test_handles_multiple_tool_calls(self):
        """finalise_tool_calls handles multiple tool calls."""
        raw = {
            0: {
                "id": "call_1",
                "name": "tool1",
                "arguments": '{"a": 1}',
            },
            1: {
                "id": "call_2",
                "name": "tool2",
                "arguments": '{"b": 2}',
            },
        }
        result = finalise_tool_calls(raw)
        
        assert len(result) == 2
        assert result[0]["name"] == "tool1"
        assert result[0]["input"] == {"a": 1}
        assert result[1]["name"] == "tool2"
        assert result[1]["input"] == {"b": 2}

    def test_preserves_name_and_id(self):
        """finalise_tool_calls preserves name and id correctly."""
        raw = {
            0: {
                "id": "call_unique_id",
                "name": "unique_tool_name",
                "arguments": "{}",
            }
        }
        result = finalise_tool_calls(raw)
        
        assert result[0]["id"] == "call_unique_id"
        assert result[0]["name"] == "unique_tool_name"
