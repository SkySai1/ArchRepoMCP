"""Minimal contract-driven Forgejo provider for repository-level metadata."""

from __future__ import annotations

import json
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from arch_repo_mcp import __version__
from arch_repo_mcp.errors import ArchRepoError, ErrorCode

_ENV_FILENAMES = (".forgejo.env", "forgejo.env", "forgego.env")
_ALLOWED_ENV_KEYS = {
    "FORGEJO_URL",
    "FORGEJO_API_URL",
    "FORGEJO_TOKEN",
    "FORGEJO_USERNAME",
    "FORGEJO_ORGANIZATION",
    "FORGEJO_DEFAULT_BRANCH",
    "FORGEJO_DEFAULT_PRIVATE",
    "FORGEJO_TLS_VERIFY",
    "FORGEJO_TIMEOUT_SECONDS",
}
_REQUIRED_SWAGGER_OPERATIONS = {
    ("/version", "get"),
    ("/repos/{owner}/{repo}", "get"),
}


@dataclass(frozen=True, slots=True)
class ForgejoConfig:
    base_url: str
    api_url: str
    token: str
    username: str
    organization: str
    default_branch: str
    default_private: bool
    tls_verify: bool
    timeout_seconds: float

    def __repr__(self) -> str:
        return (
            "ForgejoConfig("
            f"base_url={self.base_url!r}, api_url={self.api_url!r}, token=<redacted>, "
            f"username={self.username!r}, organization={self.organization!r}, "
            f"default_branch={self.default_branch!r}, "
            f"default_private={self.default_private!r}, tls_verify={self.tls_verify!r}, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )


@dataclass(frozen=True, slots=True)
class ForgejoVersion:
    provider: str
    version: str

    def as_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "version": self.version}


@dataclass(frozen=True, slots=True)
class ForgejoRepository:
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool | None
    archived: bool | None
    html_url: str | None
    clone_url: str | None
    ssh_url: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "default_branch": self.default_branch,
            "private": self.private,
            "archived": self.archived,
            "html_url": self.html_url,
            "clone_url": self.clone_url,
            "ssh_url": self.ssh_url,
        }


@dataclass(frozen=True, slots=True)
class ForgejoRemoteURLs:
    repository: str
    https_url: str | None
    ssh_url: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "repository": self.repository,
            "https_url": self.https_url,
            "ssh_url": self.ssh_url,
        }


@dataclass(frozen=True, slots=True)
class SwaggerCompatibility:
    specification_version: str
    path_count: int
    required_operations: tuple[str, ...]
    missing_operations: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.missing_operations

    def as_dict(self) -> dict[str, Any]:
        return {
            "specification_version": self.specification_version,
            "path_count": self.path_count,
            "required_operations": list(self.required_operations),
            "missing_operations": list(self.missing_operations),
            "compatible": self.compatible,
        }


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class ForgejoClient:
    """Read-only first-stage Forgejo adapter with normalized safe errors."""

    def __init__(self, config: ForgejoConfig) -> None:
        self._config = config
        context = ssl.create_default_context()
        if not config.tls_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self._opener = build_opener(HTTPSHandler(context=context), _NoRedirectHandler())

    def get_version(self) -> ForgejoVersion:
        payload = self._request_json(f"{self._config.api_url}/version")
        version = _required_string(payload, "version", operation="read Forgejo version")
        return ForgejoVersion(provider="forgejo", version=version)

    def get_repository(self, repository: str) -> ForgejoRepository:
        repository_name = _validate_repository_name(repository)
        owner = quote(self._config.organization, safe="")
        name = quote(repository_name, safe="")
        payload = self._request_json(f"{self._config.api_url}/repos/{owner}/{name}")
        owner_value = payload.get("owner")
        if isinstance(owner_value, dict):
            owner_name = owner_value.get("login") or owner_value.get("username")
        else:
            owner_name = None
        return ForgejoRepository(
            owner=_optional_string(owner_name) or self._config.organization,
            name=_required_string(payload, "name", operation="read repository metadata"),
            full_name=_required_string(
                payload, "full_name", operation="read repository metadata"
            ),
            default_branch=_required_string(
                payload, "default_branch", operation="read repository metadata"
            ),
            private=_optional_boolean(payload.get("private")),
            archived=_optional_boolean(payload.get("archived")),
            html_url=_optional_string(payload.get("html_url")),
            clone_url=_optional_string(payload.get("clone_url")),
            ssh_url=_optional_string(payload.get("ssh_url")),
        )

    def repository_exists(self, repository: str) -> bool:
        try:
            self.get_repository(repository)
        except ArchRepoError as exc:
            if exc.code is ErrorCode.NOT_FOUND:
                return False
            raise
        return True

    def resolve_remote_urls(self, repository: str) -> ForgejoRemoteURLs:
        metadata = self.get_repository(repository)
        return ForgejoRemoteURLs(
            repository=metadata.full_name,
            https_url=metadata.clone_url,
            ssh_url=metadata.ssh_url,
        )

    def check_swagger_compatibility(self) -> SwaggerCompatibility:
        document = self._request_json(f"{self._config.base_url}/swagger.v1.json")
        paths = document.get("paths")
        if not isinstance(paths, dict):
            raise ArchRepoError(
                ErrorCode.PROVIDER_CAPABILITY_GAP,
                "Forgejo Swagger document does not contain an operations map",
            )
        specification_version = _optional_string(document.get("swagger"))
        if specification_version is None:
            specification_version = _optional_string(document.get("openapi")) or "unknown"
        required = tuple(
            f"{method.upper()} {path}"
            for path, method in sorted(_REQUIRED_SWAGGER_OPERATIONS)
        )
        missing = tuple(
            f"{method.upper()} {path}"
            for path, method in sorted(_REQUIRED_SWAGGER_OPERATIONS)
            if not isinstance(paths.get(path), dict) or method not in paths[path]
        )
        result = SwaggerCompatibility(
            specification_version=specification_version,
            path_count=len(paths),
            required_operations=required,
            missing_operations=missing,
        )
        if not result.compatible:
            raise ArchRepoError(
                ErrorCode.PROVIDER_CAPABILITY_GAP,
                "Forgejo Swagger is missing required provider operations",
                details={"missing_operations": list(result.missing_operations)},
            )
        return result

    def _request_json(self, url: str) -> dict[str, Any]:
        _require_same_origin(self._config.base_url, url)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"token {self._config.token}",
                "User-Agent": f"arch-repo-mcp/{__version__}",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            _raise_http_error(exc.code)
        except ssl.SSLCertVerificationError as exc:
            raise ArchRepoError(
                ErrorCode.TLS_ERROR, "Forgejo TLS certificate validation failed"
            ) from exc
        except TimeoutError as exc:
            raise ArchRepoError(ErrorCode.TIMEOUT, "Forgejo request timed out") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                code = ErrorCode.TLS_ERROR
                message = "Forgejo TLS connection failed"
            elif isinstance(reason, TimeoutError):
                code = ErrorCode.TIMEOUT
                message = "Forgejo request timed out"
            else:
                code = ErrorCode.NETWORK_ERROR
                message = "Forgejo is unavailable"
            raise ArchRepoError(code, message) from exc
        except OSError as exc:
            raise ArchRepoError(ErrorCode.NETWORK_ERROR, "Forgejo is unavailable") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArchRepoError(
                ErrorCode.REMOTE_ERROR, "Forgejo returned an invalid JSON response"
            ) from exc
        if not isinstance(payload, dict):
            raise ArchRepoError(
                ErrorCode.REMOTE_ERROR, "Forgejo returned an unexpected response model"
            )
        return payload


def load_forgejo_config(
    environment: Mapping[str, str] | None = None,
    *,
    env_file: str | Path | None = None,
) -> ForgejoConfig:
    """Resolve Forgejo configuration without exposing secret values."""

    file_values = _read_env_file(env_file)
    source = os.environ if environment is None else environment
    values = {
        key: source[key] if key in source else file_values.get(key, "")
        for key in _ALLOWED_ENV_KEYS
    }
    base_url = _normalize_url(_required_config(values, "FORGEJO_URL"), label="Forgejo URL")
    configured_api = values["FORGEJO_API_URL"].strip()
    api_url = _normalize_url(
        configured_api or f"{base_url}/api/v1",
        label="Forgejo API URL",
    )
    _require_same_origin(base_url, api_url)
    token = _required_config(values, "FORGEJO_TOKEN")
    username = _required_config(values, "FORGEJO_USERNAME")
    organization = _required_config(values, "FORGEJO_ORGANIZATION")
    default_branch = values["FORGEJO_DEFAULT_BRANCH"].strip() or "main"
    default_private = _parse_boolean(
        values["FORGEJO_DEFAULT_PRIVATE"],
        default=False,
        label="FORGEJO_DEFAULT_PRIVATE",
    )
    tls_verify = _parse_boolean(
        values["FORGEJO_TLS_VERIFY"],
        default=True,
        label="FORGEJO_TLS_VERIFY",
    )
    timeout_text = values["FORGEJO_TIMEOUT_SECONDS"].strip()
    try:
        timeout_seconds = float(timeout_text) if timeout_text else 30.0
    except ValueError as exc:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "FORGEJO_TIMEOUT_SECONDS must be a number",
        ) from exc
    if not 1 <= timeout_seconds <= 300:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "FORGEJO_TIMEOUT_SECONDS must be between 1 and 300",
        )
    return ForgejoConfig(
        base_url=base_url,
        api_url=api_url,
        token=token,
        username=username,
        organization=organization,
        default_branch=default_branch,
        default_private=default_private,
        tls_verify=tls_verify,
        timeout_seconds=timeout_seconds,
    )


def _read_env_file(env_file: str | Path | None) -> dict[str, str]:
    if env_file is None:
        path = next((Path(name) for name in _ENV_FILENAMES if Path(name).is_file()), None)
        if path is None:
            return {}
    else:
        path = Path(env_file)
        if not path.is_file():
            raise ArchRepoError(
                ErrorCode.NOT_FOUND,
                "Forgejo environment file was not found",
                details={"path": str(path)},
            )
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED, "Forgejo environment file could not be read"
        ) from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Forgejo environment file contains an invalid line",
                details={"line": line_number},
            )
        key, value = (part.strip() for part in line.split("=", maxsplit=1))
        if key not in _ALLOWED_ENV_KEYS:
            continue
        if key in values:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Forgejo environment file contains a duplicate key",
                details={"line": line_number, "key": key},
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _required_config(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            f"Required Forgejo setting is missing: {key}",
        )
    return value


def _normalize_url(value: str, *, label: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, f"{label} is not valid") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, f"{label} is not valid")
    return value.rstrip("/")


def _require_same_origin(base_url: str, target_url: str) -> None:
    base = urlsplit(base_url)
    target = urlsplit(target_url)
    if (base.scheme.casefold(), base.hostname, base.port) != (
        target.scheme.casefold(),
        target.hostname,
        target.port,
    ):
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Forgejo API and resource URLs must use the configured origin",
        )


def _parse_boolean(value: str, *, default: bool, label: str) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ArchRepoError(ErrorCode.VALIDATION_ERROR, f"{label} must be a boolean")


def _validate_repository_name(repository: str) -> str:
    if (
        not repository
        or repository.strip() != repository
        or repository in {".", ".."}
        or "/" in repository
        or "\\" in repository
        or "\0" in repository
    ):
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Repository name is not valid")
    return repository


def _required_string(payload: Mapping[str, Any], key: str, *, operation: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ArchRepoError(
            ErrorCode.REMOTE_ERROR,
            f"Forgejo returned an invalid model during {operation}",
        )
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _raise_http_error(status: int) -> None:
    mapping = {
        401: (ErrorCode.AUTHENTICATION_ERROR, "Forgejo authentication failed"),
        403: (ErrorCode.PERMISSION_DENIED, "Forgejo permission was denied"),
        404: (ErrorCode.NOT_FOUND, "Forgejo resource was not found"),
        408: (ErrorCode.TIMEOUT, "Forgejo request timed out"),
        501: (
            ErrorCode.PROVIDER_CAPABILITY_GAP,
            "Forgejo does not support the requested capability",
        ),
    }
    code, message = mapping.get(
        status,
        (ErrorCode.REMOTE_ERROR, "Forgejo request failed"),
    )
    raise ArchRepoError(code, message, details={"status": status})
