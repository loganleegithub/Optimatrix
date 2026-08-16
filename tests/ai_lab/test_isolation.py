from pathlib import Path

import pytest

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    SOURCE_REPOSITORY,
    ValidationError,
    isolated_path,
)
from optimatrix.ai_lab.memory import AiLabMemoryStore


def test_integrated_source_and_separate_durable_root(tmp_path) -> None:
    assert SOURCE_REPOSITORY.name == "Optimatrix"
    assert (SOURCE_REPOSITORY / "src" / "optimatrix" / "ai_lab").is_dir()
    assert isolated_path(AI_LAB_DURABLE_ROOT) == AI_LAB_DURABLE_ROOT.resolve()
    assert AiLabMemoryStore(tmp_path / "ai-lab").root == (tmp_path / "ai-lab").resolve()


@pytest.mark.parametrize(
    "path",
    (
        SOURCE_REPOSITORY / "build" / "ai-lab",
        Path("/Users/logan/Optimatrix/build/ai-lab"),
        Path("/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2"),
    ),
)
def test_lab_cannot_write_repository_or_runtime_roots(path) -> None:
    with pytest.raises(ValidationError, match="outside the AI Lab boundary"):
        isolated_path(path)
