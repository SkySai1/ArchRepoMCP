from __future__ import annotations

import pytest

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.forgejo import ForgejoClient, load_forgejo_config

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def forgejo_client() -> ForgejoClient:
    try:
        config = load_forgejo_config()
    except ArchRepoError as exc:
        if exc.code in {ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR}:
            pytest.skip("Forgejo integration configuration is not available")
        raise
    return ForgejoClient(config)


def test_forgejo_connection_and_version(forgejo_client: ForgejoClient) -> None:
    result = forgejo_client.get_version()

    assert result.provider == "forgejo"
    assert result.version.strip()


def test_target_forgejo_swagger_has_required_operations(
    forgejo_client: ForgejoClient,
) -> None:
    result = forgejo_client.check_swagger_compatibility()

    assert result.compatible
    assert result.path_count > 0
    assert result.missing_operations == ()
