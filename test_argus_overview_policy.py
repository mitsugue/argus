"""Reuse is stable across display releases and invalidates on generation changes."""
import pytest
from argus_overview_policy import GENERATION_FILES, generation_revision


@pytest.fixture
def source(tmp_path):
    generation_revision.cache_clear()
    for name in GENERATION_FILES:
        (tmp_path / name).write_text('original generation implementation\n')
    yield tmp_path
    generation_revision.cache_clear()


def test_release_and_frontend_changes_preserve_reusable_policy(source):
    before = generation_revision(str(source))
    (source / 'product-version.json').write_text('{"productVersion":"v99.0.1"}')
    (source / 'presentation.css').write_text('body { color: white; }')
    generation_revision.cache_clear()  # simulate a new deployment process
    assert generation_revision(str(source)) == before


@pytest.mark.parametrize('name', GENERATION_FILES)
def test_each_generation_dependency_invalidates_reuse(source, name):
    before = generation_revision(str(source))
    (source / name).write_text('changed generation implementation\n')
    generation_revision.cache_clear()
    assert generation_revision(str(source)) != before


def test_missing_generation_code_cannot_reuse_old_explanation(source):
    (source / GENERATION_FILES[0]).unlink()
    with pytest.raises(FileNotFoundError):
        generation_revision(str(source))
