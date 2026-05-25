"""Tests for the CLI entry point."""
import os
import tempfile
from unittest.mock import patch
from src.cli.main import cli, _handle_deploy


class TestCli:
    def test_init_returns_zero(self):
        with patch("sys.argv", ["cli", "init", "myproject"]):
            assert cli() == 0

    def test_deploy_with_valid_manifest_returns_zero(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
            manifest = f.name
        try:
            with patch("sys.argv", ["cli", "deploy", manifest]):
                assert cli() == 0
        finally:
            os.unlink(manifest)

    def test_deploy_with_missing_manifest_returns_one(self):
        with patch("sys.argv", ["cli", "deploy", "/nonexistent/manifest.yaml"]):
            assert cli() == 1

    def test_status_returns_zero(self):
        with patch("sys.argv", ["cli", "status"]):
            assert cli() == 0

    def test_logs_returns_zero(self):
        with patch("sys.argv", ["cli", "logs", "agent-123"]):
            assert cli() == 0

    def test_no_command_returns_one(self):
        with patch("sys.argv", ["cli"]):
            assert cli() == 1

    def test_handle_deploy_missing_file_returns_one(self):
        assert _handle_deploy("/nonexistent/manifest.yaml") == 1

    def test_handle_deploy_existing_file_returns_zero(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml") as f:
            manifest = f.name
        try:
            assert _handle_deploy(manifest) == 0
        finally:
            os.unlink(manifest)
