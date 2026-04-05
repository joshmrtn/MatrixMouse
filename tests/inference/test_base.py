"""
tests/inference/test_base.py

Tests for inference exception hierarchy, including the
SummarizationUnavailableError added in Issue #32.
"""

import pytest

from matrixmouse.inference.base import LLMBackendError, SummarizationUnavailableError


class TestSummarizationUnavailableError:
    """Tests for SummarizationUnavailableError — Issue #32."""

    def test_summarization_unavailable_error_is_llm_backend_error(self):
        """Must be a subclass of LLMBackendError so loop.py re-raises it."""
        assert issubclass(SummarizationUnavailableError, LLMBackendError)

    def test_summarization_unavailable_error_caught_by_base_class(self):
        """Confirm it is caught by 'except LLMBackendError' blocks."""
        try:
            raise SummarizationUnavailableError("test")
        except LLMBackendError:
            pass  # Expected path
        else:
            pytest.fail("Should have been caught as LLMBackendError")

    def test_summarization_unavailable_error_message(self):
        """Confirm it has a readable message."""
        msg = "All summarizer cascade entries are unavailable."
        err = SummarizationUnavailableError(msg)
        assert msg in str(err)
