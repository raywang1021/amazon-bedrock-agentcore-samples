"""Unit tests for geo_storage Lambda handler (mocked DDB)."""

import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra", "lambda"))


class TestStorageLambda:
    def setup_method(self):
        """Mock DDB before importing handler."""
        self.mock_table = MagicMock()
        self.mock_dynamodb = MagicMock()
        self.mock_dynamodb.Table.return_value = self.mock_table

        self.patches = [
            patch("boto3.resource", return_value=self.mock_dynamodb),
        ]
        for p in self.patches:
            p.start()

        # Force reimport with mocked boto3
        if "geo_storage" in sys.modules:
            del sys.modules["geo_storage"]
        import geo_storage
        self.handler = geo_storage.handler

    def teardown_method(self):
        for p in self.patches:
            p.stop()
        if "geo_storage" in sys.modules:
            del sys.modules["geo_storage"]

    def test_store_success(self):
        self.mock_table.put_item.return_value = {}
        event = {
            "url_path": "/test/page",
            "geo_content": "<html>GEO content</html>",
            "original_url": "https://example.com/test/page",
            "content_type": "text/html; charset=utf-8",
        }
        result = self.handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "stored"
        assert body["url_path"] == "/test/page"
        self.mock_table.put_item.assert_called_once()

    def test_missing_url_path(self):
        event = {"geo_content": "<html>content</html>"}
        result = self.handler(event, None)
        assert result["statusCode"] == 400

    def test_missing_geo_content(self):
        event = {"url_path": "/test"}
        result = self.handler(event, None)
        assert result["statusCode"] == 400

    def test_empty_event(self):
        result = self.handler({}, None)
        assert result["statusCode"] == 400

    def test_host_field_included(self):
        self.mock_table.put_item.return_value = {}
        event = {
            "url_path": "/test",
            "geo_content": "<html>content</html>",
            "host": "example.com",
        }
        result = self.handler(event, None)
        assert result["statusCode"] == 200
        call_args = self.mock_table.put_item.call_args
        item = call_args[1]["Item"] if "Item" in call_args[1] else call_args[0][0]
        assert item["host"] == "example.com"
        # Composite key: host#path
        assert item["url_path"] == "example.com#/test"

    def test_composite_key_without_host(self):
        self.mock_table.put_item.return_value = {}
        event = {
            "url_path": "/test",
            "geo_content": "<html>content</html>",
        }
        result = self.handler(event, None)
        assert result["statusCode"] == 200
        call_args = self.mock_table.put_item.call_args
        item = call_args[1]["Item"] if "Item" in call_args[1] else call_args[0][0]
        # No host → key is just the path (backward compatible)
        assert item["url_path"] == "/test"

    def test_generation_duration_stored(self):
        self.mock_table.put_item.return_value = {}
        event = {
            "url_path": "/test",
            "geo_content": "<html>content</html>",
            "generation_duration_ms": 5000,
        }
        result = self.handler(event, None)
        assert result["statusCode"] == 200
        call_args = self.mock_table.put_item.call_args
        item = call_args[1]["Item"] if "Item" in call_args[1] else call_args[0][0]
        assert "generation_duration_ms" in item

    def test_ddb_error(self):
        self.mock_table.put_item.side_effect = Exception("DDB write failed")
        event = {
            "url_path": "/test",
            "geo_content": "<html>content</html>",
        }
        result = self.handler(event, None)
        assert result["statusCode"] == 500

    def test_json_string_payload(self):
        self.mock_table.put_item.return_value = {}
        event = json.dumps({
            "url_path": "/test",
            "geo_content": "<html>content</html>",
        })
        result = self.handler(event, None)
        assert result["statusCode"] == 200
