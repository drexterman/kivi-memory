from __future__ import annotations

import os
import re
from typing import Any

from app.memory.models import MemoryCandidate
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file if present


SYSTEM_INSTRUCTIONS = """
You extract durable semantic memory from a user's transcript.

Memory types:
- FACT: explicitly established stable information about a project, person, tool,
  decision, setup, or other entity.
- PREFERENCE: an explicit statement about how the user likes or wants things done.
- EPISODE: a meaningful time-bound event, meeting outcome, decision, or milestone.

Rules:
1. Only remember information that is useful beyond the current utterance.
2. Do not store greetings, filler, transient mood, one-off logistics, or noise.
3. Never turn an observation into a preference or fact by inference.
4. "I am thinking about X" is uncertain/pending, not a replacement for the current state.
5. Evidence must be a short verbatim span from the supplied transcript.
6. If there is no durable memory, set should_remember=false.
7. Certainty must reflect the transcript: explicit, inferred, or uncertain.
8. For FACT/PREFERENCE use attribute + value. For EPISODE use summary.
9. Do not invent names, dates, relationships, or values not supported by the transcript.
10. For project technology/database facts, normalize the semantic attribute: use "database" for the database/storage technology of a project.
11. Keep the entity in subject and the property in attribute. Do not combine them into one field.
12. If a statement describes a possible future change ("might", "may", "thinking about", "considering"), set certainty="uncertain" and do not represent the future value as the current state.
13. Repeated statements about an existing fact should describe the same subject and attribute so the resolver can retain the existing memory.
"""


def _fallback_extract(text: str) -> MemoryCandidate:
    """Conservative local extractor used when no LLM provider is configured.

    The fallback is intentionally semantic-pattern based rather than a collection
    of one-off examples. It normalizes common forms of established state,
    explicit changes, pending changes, preferences, and decisions.
    """
    s = " ".join(text.split()).strip()
    if not s:
        return MemoryCandidate(
            should_remember=False,
            type=None,
            title="",
            subject="",
            certainty="explicit",
            reason="Empty transcript contains no durable information.",
            evidence="",
        )

    # Pending changes must be recognized before established changes.
    pending = re.search(
        r"\b(?:i|we)\s+(?:am|are|'m|'re)\s+"
        r"(?:thinking about|considering|planning(?:\s+on)?)\s+"
        r"(?:switching|moving|changing)\s+"
        r"(?P<subject>[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*)\s+"
        r"(?:to|onto)\s+(?P<value>[^.!?,]+)",
        s,
        re.IGNORECASE,
    )
    if pending:
        subject = pending.group("subject").strip()
        value = pending.group("value").strip()
        return MemoryCandidate(
            should_remember=True,
            type="FACT",
            title=f"{subject} pending change",
            subject=subject,
            attribute="technology",
            value=value,
            certainty="uncertain",
            reason="The transcript describes a possible future change, not an established change.",
            evidence=pending.group(0).strip(),
        )

    # Explicit state changes. Handle both "switched X to Y" and "changed X from A to B".
    switched = re.search(
        r"\b(?:i|we)\s+(?:have\s+)?(?:switched|moved|changed)\s+"
        r"(?P<subject>[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*?)\s+"
        r"(?:from\s+[^.!?,]+\s+)?(?:to|onto)\s+"
        r"(?P<value>[^.!?,]+?)(?:\s+because\s+.*)?$",
        s,
        re.IGNORECASE,
    )
    if switched:
        subject = switched.group("subject").strip()
        value = switched.group("value").strip()
        return MemoryCandidate(
            should_remember=True,
            type="FACT",
            title=f"{subject} setup",
            subject=subject,
            attribute="technology",
            value=value,
            certainty="explicit",
            reason="The transcript explicitly records a change of project setup.",
            evidence=switched.group(0).strip(),
        )

    # Established technology/state. This intentionally includes "still", "continues",
    # and "remains" so repeated evidence reaches the resolver and can be RETAINed.
    established = re.search(
        r"\b(?:for|in)\s+(?P<subject>[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*?)\s+"
        r"(?:we\s+are\s+|we\s+)?(?:still\s+|currently\s+|now\s+|continue\s+to\s+|remain\s+on\s+)?"
        r"(?:using|use|running)\s+(?P<value>[^.!?,]+)",
        s,
        re.IGNORECASE,
    )
    if established:
        subject = established.group("subject").strip()
        value = established.group("value").strip()
        return MemoryCandidate(
            should_remember=True,
            type="FACT",
            title=f"{subject} setup",
            subject=subject,
            attribute="technology",
            value=value,
            certainty="explicit",
            reason="The transcript explicitly establishes the project's current technology/setup.",
            evidence=established.group(0).strip(),
        )

    # Equivalent project-state phrasing: "Atlas is on DuckDB" / "Atlas uses DuckDB".
    state = re.search(
        r"\b(?P<subject>[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*)\s+"
        r"(?:is\s+(?:currently\s+|still\s+)?on|uses|is\s+using|runs\s+on)\s+"
        r"(?P<value>[^.!?,]+)",
        s,
        re.IGNORECASE,
    )
    if state:
        subject = state.group("subject").strip()
        value = state.group("value").strip()
        return MemoryCandidate(
            should_remember=True,
            type="FACT",
            title=f"{subject} setup",
            subject=subject,
            attribute="technology",
            value=value,
            certainty="explicit",
            reason="The transcript explicitly states the project's current setup.",
            evidence=state.group(0).strip(),
        )

    # Explicit preferences. Only treat preference language as preference; do not infer
    # preferences from behavior such as "I worked late".
    pref = re.search(
        r"\b(?:i|we)\s+(?:prefer|like|want)\s+(?P<value>.+?)(?:[.!?]|$)",
        s,
        re.IGNORECASE,
    )
    if pref:
        value = pref.group("value").strip()
        return MemoryCandidate(
            should_remember=True,
            type="PREFERENCE",
            title="User preference",
            subject="User",
            attribute="preference",
            value=value,
            certainty="explicit",
            reason="The transcript explicitly states a durable preference.",
            evidence=pref.group(0).strip(),
        )

    # Meaningful explicit decisions.
    episode = re.search(
        r"\b(?:we\s+)?(?:decided|agreed)\s+(?:that\s+)?(?P<summary>[^.!?]+)",
        s,
        re.IGNORECASE,
    )
    if episode:
        summary = episode.group("summary").strip()
        return MemoryCandidate(
            should_remember=True,
            type="EPISODE",
            title="Decision",
            subject="Decision",
            summary=summary,
            certainty="explicit",
            reason="The transcript records an explicit decision.",
            evidence=episode.group(0).strip(),
        )

    return MemoryCandidate(
        should_remember=False,
        type=None,
        title="",
        subject="",
        certainty="explicit",
        reason="No durable fact, preference, or meaningful episode was detected.",
        evidence=s,
    )


def extract_memory(text: str) -> tuple[MemoryCandidate, dict[str, Any]]:
    api_key = os.getenv("API_KEY")
    if not api_key:
        candidate = _fallback_extract(text)
        return candidate, {
            "provider": "fallback",
            "model": None,
        }
    try:
        from openai import OpenAI
        base_url = os.getenv(
                "BASE_URL",
                "https://openrouter.ai/api/v1",
                )
        client = OpenAI(api_key=api_key,base_url=base_url)
        schema = MemoryCandidate.model_json_schema()

        # response = client.responses.create(
        #     model="minimax/minimax-m3:free",
        #     instructions=SYSTEM_INSTRUCTIONS,
        #     input=text,
        #     text={
        #         "format": {
        #             "type": "json_schema",
        #             "name": "memory_candidate",
        #             "schema": schema,
        #             "strict": True,
        #         }
        #     },
        # )

        response = client.chat.completions.create(
            model="mistralai/mistral-small-3.2-24b-instruct",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "memory_candidate",
                    "schema": schema,
                    "strict": True,
                }
            },
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": text}
            ]
        )
        response_text  = response.choices[0].message.content
        # print("RAW LLM RESPONSE:")
        # print(response_text)
        response_text = response_text.strip()

        if response_text.startswith("```"):
            response_text = re.sub(
                r"^```(?:json)?\s*",
                "",
                response_text,
                flags=re.IGNORECASE,
            )
            response_text = re.sub(r"\s*```$", "", response_text).strip()

        candidate = MemoryCandidate.model_validate_json(response_text)
        return candidate, {
            "provider": "OpenRouter",
            "model": os.getenv("MODEL", "gpt-5.6-luna"),
            "response_id": getattr(response, "id", None),
            "usage": getattr(response, "usage", None),
        }
    except Exception as exc:
        # Do not make the product unusable because the external model is down.
        # The fallback is conservative and the failure is returned for observability.
        candidate = _fallback_extract(text)
        return candidate, {
            "provider": "fallback",
            "model": None,
            "llm_error": str(exc),
        }
