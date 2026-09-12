"""Observe SDK invocations without changing provider behavior or budget accounting."""
from datetime import datetime, timezone
from collections.abc import Mapping
import uuid
from argus_ai_usage_receipt import make_receipt


def field(value, name):
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def count(value):
    return value if type(value) is int and value >= 0 else None


def usage(response, provider):
    if provider == 'openai':
        value=field(response,'usage')
        inp=count(field(value,'input_tokens'))
        if inp is None:inp=count(field(value,'prompt_tokens'))
        out=count(field(value,'output_tokens'))
        if out is None:out=count(field(value,'completion_tokens'))
        detail=field(value,'input_tokens_details') or field(value,'prompt_tokens_details')
        cached=count(field(detail,'cached_tokens'))
        model=field(response,'model')
    else:
        value=field(response,'usage_metadata');inp=count(field(value,'prompt_token_count'))
        candidates=count(field(value,'candidates_token_count'));thoughts=count(field(value,'thoughts_token_count'))
        out=candidates+thoughts if candidates is not None and thoughts is not None else None
        cached=count(field(value,'cached_content_token_count'));model=field(response,'model_version')
    if cached is not None and inp is not None and cached>inp:cached=None
    return {'inputTokens':inp,'outputTokens':out,'cachedInputTokens':cached,
            'returnedModel':model if isinstance(model,str) and 0<len(model)<=160 else None}


def observe(invoke, *, provider, feature, requested_model, record, estimate,
            attempt=None, source_ref=None, clock=None, on_record_error=None):
    """One SDK invocation, including its internal retries; no retry is added here.

    A success means a provider response, not validation or publication of its
    explanation. Errors have unknown usage/cost, never an invented zero bill.
    Recorder failures must not cause the caller to repeat a paid request.
    """
    clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
    started=clock();identity='sdk:'+uuid.uuid4().hex;response=None;outcome='provider_error';error_class=None
    try:
        response=invoke();outcome='success';return response
    except Exception as exc:
        error_class=type(exc).__name__;raise
    finally:
        try:
            values=usage(response,provider);cost=None
            if outcome=='success' and values['inputTokens'] is not None and values['outputTokens'] is not None:
                try:cost=estimate(values['returnedModel'],values['inputTokens'],values['outputTokens'])
                except Exception:cost=None
            row=make_receipt(call_id=identity,provider=provider,feature=feature,started_at=started,
                completed_at=clock(),requested_model=requested_model,returned_model=values['returnedModel'],
                outcome=outcome,input_tokens=values['inputTokens'],output_tokens=values['outputTokens'],
                cached_input_tokens=values['cachedInputTokens'],estimated_cost_usd=cost,provider_called=True,
                attempt=attempt,source_ref=source_ref,error_class=error_class,
                provider_request_id=field(response,'id') if provider=='openai' else field(response,'response_id'))
            record(row)
        except Exception as exc:
            if on_record_error:
                try:on_record_error(type(exc).__name__)
                except Exception:pass
