"""Keep explicit repository paths independent of the launching Git process."""

import os

_REPOSITORY_VARIABLES = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_SHALLOW_FILE",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_IMPLICIT_WORK_TREE",
}


def git_environment() -> dict[str, str]:
    """Preserve authentication and user configuration, excluding repository overrides."""

    return {key: value for key, value in os.environ.items() if key not in _REPOSITORY_VARIABLES}
