from __future__ import annotations

from typing import Callable

from integrity.engines import citations, content_check, doi_detection, version_diff
from integrity.engines.base import StageInput, StageOutput

# (engine name, version) -> callable. A workflow referencing an unknown pair fails loudly.
ENGINES: dict[tuple[str, str], Callable[[StageInput], StageOutput]] = {
    (content_check.NAME, content_check.VERSION): content_check.run,
    (doi_detection.NAME, doi_detection.VERSION): doi_detection.run,
    (citations.NAME, citations.VERSION): citations.run,
    (version_diff.NAME, version_diff.VERSION): version_diff.run,
}

# Engines whose input must include the previous version of the document.
NEEDS_PREVIOUS: set[tuple[str, str]] = {(version_diff.NAME, version_diff.VERSION)}
