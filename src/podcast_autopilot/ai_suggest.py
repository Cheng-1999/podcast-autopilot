"""Optional AI-assisted cut suggestions.

Shells out to a locally installed AI coding-agent CLI (e.g. `claude -p`,
`codex exec`) the same way the sibling `agentboard` project drives those
CLIs for code review: feed it a prompt over stdin, read structured JSON back
from stdout. Nothing here is invoked unless a profile sets
`ai_suggest.command` explicitly (see config.py), and nothing this module
returns is ever written to a plan directly -- every suggestion is validated
with `audit.audit_plan` and surfaced to the human in the Review page for a
one-click accept/discard, the same trust boundary as the pause/filler/clip
detectors already in this pipeline.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 120.0
MAX_SUGGESTIONS = 20


class AISuggestError(RuntimeError):
    pass


@dataclass
class CutSuggestion:
    start: float
    end: float
    reason: str


def build_prompt(segments: list[dict], duration: float) -> str:
    lines = [
        "You are reviewing a podcast episode transcript to find spans of audio "
        "worth cutting: redundant retakes of the same sentence, off-topic "
        "tangents, or a mistake the speaker immediately corrected. Pauses and "
        "filler words (um, uh, etc.) are already handled by other tools -- do "
        "not suggest those.",
        f"The audio is {duration:.1f} seconds long. Each line below is "
        '"[start-end] text" with timestamps in seconds.',
        "",
    ]
    for seg in segments:
        lines.append(f"[{float(seg['start']):.2f}-{float(seg['end']):.2f}] {seg.get('text', '')}")
    lines.append("")
    lines.append(
        "Reply with ONLY a JSON array (no prose, no markdown fences) of objects "
        '{"start": <seconds>, "end": <seconds>, "reason": "<short reason>"}, one '
        "per span you recommend cutting. Reply with [] if nothing stands out."
    )
    return "\n".join(lines)


def _extract_json_array(text: str) -> list:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise AISuggestError(f"AI CLI did not return a JSON array; got: {text[:500]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AISuggestError(f"AI CLI returned invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise AISuggestError("AI CLI's JSON reply was not a list")
    return data


def run_ai_suggest(
    command: list[str],
    prompt: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[CutSuggestion]:
    try:
        proc = subprocess.run(
            list(command),
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise AISuggestError(f"AI CLI command not found: {command!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AISuggestError(f"AI CLI timed out after {timeout_s}s") from exc

    if proc.returncode != 0:
        raise AISuggestError(f"AI CLI exited {proc.returncode}: {proc.stderr[:500]}")

    raw = _extract_json_array(proc.stdout)[:MAX_SUGGESTIONS]
    suggestions: list[CutSuggestion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry["start"])
            end = float(entry["end"])
        except (KeyError, TypeError, ValueError):
            continue
        reason = str(entry.get("reason") or "ai-suggested")
        suggestions.append(CutSuggestion(start=start, end=end, reason=reason))
    return suggestions
