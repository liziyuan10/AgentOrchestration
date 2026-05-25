"""Tests for the Orchestrator API client SDK."""
from unittest.mock import patch, MagicMock
from src.sdk.client import OrchestratorClient


class TestOrchestratorClient:
    def setup_method(self):
        self.client = OrchestratorClient(
            base_url="https://test.api",
            api_key="test-key",
        )

    @patch("src.sdk.client.urlopen")
    def test_request_returns_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"id": "abc", "status": "running"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = self.client._request("GET", "/agents")
        assert result == {"id": "abc", "status": "running"}

    @patch("src.sdk.client.urlopen")
    def test_request_204_returns_ok(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = self.client._request("DELETE", "/agents/abc")
        assert result == {"status": "ok"}

    @patch("src.sdk.client.urlopen")
    def test_request_empty_body_returns_ok(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = self.client._request("DELETE", "/agents/abc")
        assert result == {"status": "ok"}
