"""
Shared LLM-calling helper: one schema-enforced call, with rate limiting and
retry/backoff, used by every stage that talks to an LLM (generate_cvs.py,
extract.py, score.py, draft.py).

Two providers are wired up, chosen at call time by the LLM_PROVIDER env var
(gemini or groq, default gemini) - see docs/LEARNING.md for the full story.
Neither one is free of real limits, and they bind on different axes:
  - Groq: 14,400 requests/day, no deposit required - but also a hard 200,000
    TOKENS/day cap on this model, confirmed live when a 62-candidate
    generation run plus a partial extraction run exhausted it in well under
    100 calls. That cap doesn't move no matter how calls are spaced out.
  - Gemini (gemini-3.5-flash-lite): free tier is request-count limited
    (~1,000 requests/day, ~15/minute per third-party sources - Google no
    longer publishes static free-tier numbers, they're account-specific via
    the AI Studio dashboard) rather than token-volume limited, which fits
    this project's per-call token size (full CV text + schema) far better.
(dedupe.py stays on Gemini regardless of LLM_PROVIDER: Groq has no
embeddings endpoint at all, so that was never a real choice.)

Every Pydantic schema passed through here MUST:
  1. Set `model_config = ConfigDict(extra="forbid")` (and so must every nested
     model) - Groq's strict mode requires `additionalProperties: false`
     everywhere in the schema, which Pydantic only emits when extra fields
     are forbidden. Gemini accepts this shape too, so one schema serves both.
  2. Have no Optional/nullable fields - Groq's strict mode requires every
     property to be listed in `required`, and a field with a default (which
     is how Pydantic represents "optional") is excluded from `required`. Use
     a required sentinel instead (e.g. a 3-way string enum, or an empty
     string for "no value") - see ExtractedProfile.right_to_work in
     extract.py for a worked example. Gemini has no such requirement, but a
     schema that satisfies Groq's stricter rule is still valid for Gemini,
     so this constraint is safe to keep even when Groq isn't the active
     provider - one schema, either backend, no per-provider branching needed
     anywhere outside this file.
Both were confirmed by testing directly against the API, not assumed from
documentation - the exact error messages differ from Gemini's, and finding
that out by running a request was faster and more reliable than guessing.
"""

import os
import time
from typing import TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import types
from groq import Groq
from pydantic import BaseModel

load_dotenv()

DEFAULT_PROVIDER = "gemini"

GROQ_MODEL = "openai/gpt-oss-120b"          # confirmed live: strict structured outputs work, including nested objects
GEMINI_MODEL = "gemini-3.5-flash-lite"      # confirmed live across Days 1-4 before the Groq detour

# Spacing is provider-specific: Groq's free tier is ~30 requests/minute,
# Gemini's is ~15/minute (see module docstring) - each gets its own pace
# rather than one shared constant either provider would be wrong for.
MIN_SECONDS_BETWEEN_CALLS = {"groq": 2.0, "gemini": 5.0}
MAX_RETRIES = 4

T = TypeVar("T", bound=BaseModel)

_groq_client: Groq | None = None
_gemini_client: genai.Client | None = None
_last_call_at: dict[str, float] = {"groq": 0.0, "gemini": 0.0}


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env.")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _call_groq(prompt: str, schema: type[T], temperature: float, model: str) -> T:
    client = _get_groq_client()
    json_schema = schema.model_json_schema()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": True},
        },
        temperature=temperature,
    )
    return schema.model_validate_json(response.choices[0].message.content)


def _strip_additional_properties(node):
    """Gemini's schema format has no `additionalProperties` field at all -
    confirmed live: passing a Pydantic class straight through (as the
    pre-Groq code did) now 400s, because `extra="forbid"` (added for Groq's
    strict mode) makes the SDK's auto-conversion emit that field, and
    Gemini's backend rejects the unknown field outright. Stripping it from
    the plain JSON schema dict before sending is the fix - `$defs`/`$ref`
    for nested models still resolve correctly with it removed.

    Deliberately leaves `title` alone despite an earlier attempt to strip
    that too "for tidiness": `title` is also a real field name here
    (Employment.title, the job title) and JSON Schema uses the same key for
    its own per-node metadata, so a blanket `.pop("title")` was silently
    deleting the schema entry for any field literally named "title" -
    caught live when Gemini rejected the resulting schema as inconsistent
    (`required` referenced a property stripping had just removed). Not
    worth the collision risk for a field that costs nothing left in place.
    """
    if isinstance(node, dict):
        node.pop("additionalProperties", None)
        for value in node.values():
            _strip_additional_properties(value)
    elif isinstance(node, list):
        for value in node:
            _strip_additional_properties(value)
    return node


def _call_gemini(prompt: str, schema: type[T], temperature: float, model: str) -> T:
    client = _get_gemini_client()
    gemini_schema = _strip_additional_properties(schema.model_json_schema())
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gemini_schema,
            temperature=temperature,
        ),
    )
    # response.parsed is only populated when response_schema is the Pydantic
    # class itself; a plain dict schema (required here) comes back as JSON
    # text only, so validate it explicitly.
    return schema.model_validate_json(response.text)


_PROVIDERS = {
    "groq": (_call_groq, GROQ_MODEL),
    "gemini": (_call_gemini, GEMINI_MODEL),
}


def call_structured(prompt: str, schema: type[T], temperature: float, model: str | None = None) -> T:
    """One schema-enforced call, with backoff. Raises if it never succeeds.

    Provider is read from LLM_PROVIDER fresh on every call (not cached at
    import time), so switching is a one-line .env edit or an
    `LLM_PROVIDER=groq python src/whatever.py` override for a single run -
    no code change either way.
    """
    provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        raise RuntimeError(f"Unknown LLM_PROVIDER '{provider}'. Choices: {sorted(_PROVIDERS)}")
    call_fn, default_model = _PROVIDERS[provider]
    model = model or default_model
    min_seconds = MIN_SECONDS_BETWEEN_CALLS[provider]

    for attempt in range(MAX_RETRIES):
        wait = min_seconds - (time.time() - _last_call_at[provider])
        if wait > 0:
            time.sleep(wait)

        try:
            _last_call_at[provider] = time.time()
            return call_fn(prompt, schema, temperature, model)

        except Exception as exc:                      # noqa: BLE001
            backoff = 2 ** attempt * 5
            print(f"    attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                  f"retrying in {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts")
