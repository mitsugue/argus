"""Observe existing candidate reuse without changing numerical engine identity."""
from argus_market_artifact_store import payload_sha256

GROUPS = ('prices', 'states', 'conditions', 'reactions', 'research', 'calendar')


def _key(value):
    return value if type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value) else None


def _candidate(cache):
    value = cache.get('sealedCandidates')
    return value if isinstance(value, dict) else {}


def begin(cache, groups):
    """Only small hashes survive; no prices, rows or candidate graph is owned."""
    cache.pop('candidatePreparation', None)
    previous = cache.get('preparationInputDigests')
    previous = {k: _key(previous.get(k)) for k in GROUPS} if isinstance(previous, dict) else {}
    digests = {}
    try:
        if (set(groups) != set(GROUPS) or len(groups['prices']) > 3000
                or len(groups['calendar']) > 3000
                or sum(len(groups[k]) for k in ('states', 'conditions', 'reactions', 'research')) > 60000):
            raise ValueError('bounded_comparison_observation_required')
        for name in GROUPS:
            digests[name] = payload_sha256(groups[name], depth=3)
    except (TypeError, ValueError, OverflowError):
        digests = {}
    return {'previousKey': _key(_candidate(cache).get('key')),
            'previousInputs': previous, 'inputs': digests}


def finish(cache, observation):
    """Input-group drift is evidence, not an assertion of which field caused it."""
    current = _candidate(cache)
    key = _key(current.get('key'))
    inputs, previous = observation['inputs'], observation['previousInputs']
    if not key or len(inputs) != len(GROUPS):
        status = 'NOT_EVALUABLE'
    elif observation['previousKey'] is None:
        status = 'COLD'
    elif key == observation['previousKey']:
        status = 'REUSED'
    else:
        status = 'REBUILT'
    count = len(current.get('candidates') or ()) if status in ('COLD', 'REBUILT') else 0
    result = {'status': status,
        'changedInputs': [k for k in GROUPS if len(inputs) == len(GROUPS)
                          and previous and all(previous.values()) and previous[k] != inputs[k]],
        'builtCandidates': count if status != 'NOT_EVALUABLE' and count <= 3000 else None}
    cache['candidatePreparation'] = result
    cache['preparationInputDigests'] = inputs
    return result
