"""Bind saved explanations to generation code, not unrelated release identity."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json


# Include the provider implementation and all local explanation validators.
# Numerical inputs and their provenance remain independently bound by the
# overview input digest. No saved completion or original build is rewritten.
GENERATION_FILES = (
    'argus_overview_policy.py',
    'scanner.py',
    'argus_owner_dialogue.py',
    'argus_owner_dialogue_api.py',
    'argus_market_brief.py',
    'argus_presentation_intent.py',
    'argus_explanation_contract.py',
)


@lru_cache(maxsize=1)
def generation_revision(root: str) -> str:
    """Immutable deployment source; missing files fail closed, never reuse."""
    directory = Path(root)
    sources = {name: sha256((directory / name).read_bytes()).hexdigest()
               for name in GENERATION_FILES}
    body = {'schemaVersion': 'argus-overview-generation-code-v1', 'sources': sources}
    return sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
