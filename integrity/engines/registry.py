from __future__ import annotations

from typing import Callable

from integrity.engines import content_check, doi_detection
from integrity.engines.base import StageInput, StageOutput

# (engine name, version) -> callable. A workflow referencing an unknown pair fails loudly.
ENGINES: dict[tuple[str, str], Callable[[StageInput], StageOutput]] = {
    (content_check.NAME, content_check.VERSION): content_check.run,
    (doi_detection.NAME, doi_detection.VERSION): doi_detection.run,
}
