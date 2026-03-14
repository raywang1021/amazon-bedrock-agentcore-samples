"""Unit tests for geo_content_handler pure logic functions."""

import sys
import os

# Add Lambda code to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra", "lambda"))

from datetime import datetime, timezone, timedelta
from geo_content_handler import _is_text_content, _is_processing_stale, _get_mode, _is_purge


class TestIsTextContent:
    def test_html(self):
        assert _is_text_content("text/html") is True

    def test_html_with_charset(self):
        assert _is_text_content("text/html; charset=utf-8") is True

    def test_plain_text(self):
        assert _is_text_content("text/plain") is True

    def test_xml(self):
        assert _is_text_content("text/xml") is True

    def test_json(self):
        assert _is_text_content("application/json") is True

    def test_xhtml(self):
        assert _is_text_content("application/xhtml+xml") is True

    def test_image_png(self):
        assert _is_text_content("image/png") is False

    def test_image_jpeg(self):
        assert _is_text_content("image/jpeg") is False

    def test_pdf(self):
        assert _is_text_content("application/pdf") is False

    def test_octet_stream(self):
        assert _is_text_content("application/octet-stream") is False

    def test_none_assumes_text(self):
        assert _is_text_content(None) is True

    def test_empty_assumes_text(self):
        assert _is_text_content("") is True


class TestIsProcessingStale:
    def test_fresh_record(self):
        item = {"created_at": datetime.now(timezone.utc).isoformat()}
        assert _is_processing_stale(item) is False

    def test_stale_record(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        item = {"created_at": old.isoformat()}
        assert _is_processing_stale(item) is True

    def test_exactly_at_boundary(self):
        # Default timeout is 300s (5min)
        boundary = datetime.now(timezone.utc) - timedelta(seconds=301)
        item = {"created_at": boundary.isoformat()}
        assert _is_processing_stale(item) is True

    def test_no_created_at(self):
        assert _is_processing_stale({}) is True

    def test_invalid_timestamp(self):
        assert _is_processing_stale({"created_at": "not-a-date"}) is True


class TestGetMode:
    def test_default_passthrough(self):
        assert _get_mode({}) == "passthrough"

    def test_explicit_passthrough(self):
        assert _get_mode({"queryStringParameters": {"mode": "passthrough"}}) == "passthrough"

    def test_async(self):
        assert _get_mode({"queryStringParameters": {"mode": "async"}}) == "async"

    def test_sync(self):
        assert _get_mode({"queryStringParameters": {"mode": "sync"}}) == "sync"

    def test_invalid_mode_defaults(self):
        assert _get_mode({"queryStringParameters": {"mode": "invalid"}}) == "passthrough"

    def test_none_params(self):
        assert _get_mode({"queryStringParameters": None}) == "passthrough"


class TestIsPurge:
    def test_purge_true(self):
        assert _is_purge({"queryStringParameters": {"purge": "true"}}) is True

    def test_purge_yes(self):
        assert _is_purge({"queryStringParameters": {"purge": "yes"}}) is True

    def test_purge_1(self):
        assert _is_purge({"queryStringParameters": {"purge": "1"}}) is True

    def test_purge_false(self):
        assert _is_purge({"queryStringParameters": {"purge": "false"}}) is False

    def test_no_purge(self):
        assert _is_purge({}) is False

    def test_none_params(self):
        assert _is_purge({"queryStringParameters": None}) is False
