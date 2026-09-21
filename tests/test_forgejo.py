from __future__ import annotations

import io
import json
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.forgejo import ForgejoClient, ForgejoConfig, load_forgejo_config


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args


class _FakeOpener:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self.payload = payload
        self.requests: list[Request] = []

    def open(self, request: Request, *, timeout: float) -> _Response:
        assert timeout == 5.0
        self.requests.append(request)
        if isinstance(self.payload, Exception):
            raise self.payload
        return _Response(json.dumps(self.payload).encode("utf-8"))


def _config(**overrides: object) -> ForgejoConfig:
    values: dict[str, object] = {
        "base_url": "https://forgejo.example.invalid",
        "api_url": "https://forgejo.example.invalid/api/v1",
        "token": "secret-token",
        "username": "agent",
        "organization": "architecture-tests",
        "default_branch": "main",
        "default_private": True,
        "tls_verify": True,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return ForgejoConfig(**values)  # type: ignore[arg-type]


def _client_with_payload(
    payload: dict[str, Any] | Exception,
) -> tuple[ForgejoClient, _FakeOpener]:
    client = ForgejoClient(_config())
    opener = _FakeOpener(payload)
    client._opener = opener
    return client, opener


def test_config_loads_local_file_with_environment_precedence(tmp_path: Path) -> None:
    env_file = tmp_path / "forgejo.env"
    env_file.write_text(
        "\n".join(
            [
                "FORGEJO_URL=https://forgejo.example.invalid",
                "FORGEJO_TOKEN=file-token",
                "FORGEJO_USERNAME=file-user",
                "FORGEJO_ORGANIZATION=architecture-tests",
                "FORGEJO_DEFAULT_PRIVATE=true",
                "FORGEJO_TLS_VERIFY=yes",
            ]
        ),
        encoding="utf-8",
    )

    config = load_forgejo_config(
        {"FORGEJO_TOKEN": "environment-token"},
        env_file=env_file,
    )

    assert config.api_url == "https://forgejo.example.invalid/api/v1"
    assert config.token == "environment-token"
    assert config.default_private is True
    assert config.tls_verify is True
    assert "environment-token" not in repr(config)
    assert "file-token" not in repr(config)


@pytest.mark.parametrize(
    "environment",
    [
        {
            "FORGEJO_URL": "https://user:token@forgejo.example.invalid",
            "FORGEJO_TOKEN": "token",
            "FORGEJO_USERNAME": "agent",
            "FORGEJO_ORGANIZATION": "tests",
        },
        {
            "FORGEJO_URL": "https://forgejo.example.invalid",
            "FORGEJO_API_URL": "https://attacker.example.invalid/api/v1",
            "FORGEJO_TOKEN": "token",
            "FORGEJO_USERNAME": "agent",
            "FORGEJO_ORGANIZATION": "tests",
        },
    ],
)
def test_config_rejects_credential_urls_and_cross_origin_api(
    environment: dict[str, str],
    tmp_path: Path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    with pytest.raises(ArchRepoError) as captured:
        load_forgejo_config(environment, env_file=empty_env)

    assert captured.value.code is ErrorCode.VALIDATION_ERROR


def test_version_uses_token_header_without_returning_token() -> None:
    client, opener = _client_with_payload({"version": "16.0.5"})

    result = client.get_version()

    assert result.as_dict() == {"provider": "forgejo", "version": "16.0.5"}
    assert opener.requests[0].get_header("Authorization") == "token secret-token"
    assert "secret-token" not in str(result.as_dict())


def test_repository_metadata_and_remote_urls_are_normalized() -> None:
    payload = {
        "owner": {"login": "architecture-tests"},
        "name": "model",
        "full_name": "architecture-tests/model",
        "default_branch": "main",
        "private": True,
        "archived": False,
        "html_url": "https://forgejo.example.invalid/architecture-tests/model",
        "clone_url": "https://forgejo.example.invalid/architecture-tests/model.git",
        "ssh_url": "ssh://git@forgejo.example.invalid/architecture-tests/model.git",
    }
    client, _ = _client_with_payload(payload)

    metadata = client.get_repository("model")
    urls = client.resolve_remote_urls("model")

    assert metadata.full_name == "architecture-tests/model"
    assert metadata.default_branch == "main"
    assert urls.repository == "architecture-tests/model"
    assert urls.https_url == payload["clone_url"]
    assert urls.ssh_url == payload["ssh_url"]


def test_swagger_compatibility_checks_required_operations() -> None:
    client, _ = _client_with_payload(
        {
            "swagger": "2.0",
            "paths": {
                "/version": {"get": {}},
                "/repos/{owner}/{repo}": {"get": {}},
                "/other": {"get": {}},
            },
        }
    )

    result = client.check_swagger_compatibility()

    assert result.compatible
    assert result.specification_version == "2.0"
    assert result.path_count == 3
    assert result.missing_operations == ()


def test_swagger_missing_operation_is_provider_capability_gap() -> None:
    client, _ = _client_with_payload(
        {"swagger": "2.0", "paths": {"/version": {"get": {}}}}
    )

    with pytest.raises(ArchRepoError) as captured:
        client.check_swagger_compatibility()

    assert captured.value.code is ErrorCode.PROVIDER_CAPABILITY_GAP
    assert captured.value.details == {
        "missing_operations": ["GET /repos/{owner}/{repo}"]
    }


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (HTTPError("url", 401, "unauthorized", {}, None), ErrorCode.AUTHENTICATION_ERROR),
        (HTTPError("url", 403, "forbidden", {}, None), ErrorCode.PERMISSION_DENIED),
        (HTTPError("url", 404, "missing", {}, None), ErrorCode.NOT_FOUND),
        (HTTPError("url", 408, "timeout", {}, None), ErrorCode.TIMEOUT),
        (HTTPError("url", 501, "unsupported", {}, None), ErrorCode.PROVIDER_CAPABILITY_GAP),
        (URLError(ssl.SSLError("certificate failure")), ErrorCode.TLS_ERROR),
        (URLError(OSError("unavailable")), ErrorCode.NETWORK_ERROR),
        (TimeoutError(), ErrorCode.TIMEOUT),
    ],
)
def test_provider_transport_failures_are_normalized(
    failure: Exception,
    expected: ErrorCode,
) -> None:
    client, _ = _client_with_payload(failure)

    with pytest.raises(ArchRepoError) as captured:
        client.get_version()

    assert captured.value.code is expected
    assert "secret-token" not in captured.value.message
    assert "secret-token" not in str(captured.value.details)
