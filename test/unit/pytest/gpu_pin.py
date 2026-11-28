"""Expected org GPU reusable workflow reference for hosted tests."""

import re

GPU_REUSABLE_TAG = "v0.4.0"
GPU_REUSABLE_MIN_TAG = "v0.4.0"
GPU_REUSABLE_PATH = "ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml"
GPU_REUSABLE = f"{GPU_REUSABLE_PATH}@{GPU_REUSABLE_TAG}"


def tag_at_least_min(tag: str) -> bool:
    component = r"(0|[1-9][0-9]*)"
    match = re.fullmatch(rf"v{component}\.{component}\.{component}", tag)
    if match is None:
        return False
    version = tuple(map(int, match.groups()))
    minimum = tuple(map(int, GPU_REUSABLE_MIN_TAG[1:].split(".")))
    return version >= minimum
