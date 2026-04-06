"""Unit tests for fetch_page_text with mocked HTTP responses."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from tools.fetch import fetch_page_text


class TestFetchPageText:
    @patch("tools.fetch.requests.get")
    def test_basic_html_extraction(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Hello World</p></body></html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_page_text("https://example.com")
        assert "Hello" in result
        assert "World" in result

    @patch("tools.fetch.requests.get")
    def test_strips_script_tags(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><script>var x=1;</script><body><p>Content</p></body></html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_page_text("https://example.com")
        assert "var x" not in result
        assert "Content" in result

    @patch("tools.fetch.requests.get")
    def test_strips_style_tags(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><style>.x{color:red}</style><body><p>Visible</p></body></html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_page_text("https://example.com")
        assert "color:red" not in result
        assert "Visible" in result

    @patch("tools.fetch.requests.get")
    def test_http_error_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_resp

        with pytest.raises(Exception, match="404"):
            fetch_page_text("https://example.com/missing")

    @patch("tools.fetch.requests.get")
    def test_user_agent_header(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>OK</body></html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        fetch_page_text("https://example.com")
        call_args = mock_get.call_args
        assert "User-Agent" in call_args[1]["headers"]
