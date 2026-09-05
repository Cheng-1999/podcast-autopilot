"""Transcript-driven clip candidates for social cuts.

Candidates are windows of 30-90s that start and end on segment boundaries at
pauses >= profile.clips.pause_threshold_s. Scoring is local, explainable and
deterministic (keyword density, questions, numbers, named-entity-like
tokens, speech rate vs. the episode median, filler penalty); an optional
LLM re-rank runs only when ANTHROPIC_API_KEY is set and never breaks the
command if it fails.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, ClipsConfig, DEFAULT_FILLER_WORDS
from .ffmpeg import measure_loudness, run_ffmpeg
from .plan import PlanItem
from .transcribe import _format_srt_timestamp

CLIPS_SCHEMA_ID = "podcast-autopilot.clips/v1"

MIN_CLIP_DURATION_S = 30.0
MAX_CLIP_DURATION_S = 90.0
MIN_PAUSE_S = 0.4
MIN_CANDIDATES = 5
MAX_CANDIDATES = 10
CLIP_FADE_S = 0.1

# Explainable, linear scoring weights: each component is a rate (per second)
# or a plain count, so no component can dominate just by candidate length.
WEIGHT_KEYWORD = 5.0
WEIGHT_QUESTION = 1.0
WEIGHT_NUMBER = 0.5
WEIGHT_ENTITY = 0.5
WEIGHT_SPEECH_RATE = 1.0
WEIGHT_FILLER_PENALTY = 3.0

_NUMBER_RE = re.compile(r"\d+")
_CAPITALIZED_RE = re.compile(r"\b[A-Z][A-Za-z]{1,}\b")
_QUOTED_RE = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]+\"")
_QUESTION_CHARS = "？?"

LLM_MODEL = "claude-opus-5"


def generate_windows(
    segments: list[dict],
    pause_threshold_s: float = MIN_PAUSE_S,
    min_duration: float = MIN_CLIP_DURATION_S,
    max_duration: float = MAX_CLIP_DURATION_S,
) -> list[tuple[int, int, float]]:
    """Every (start_idx, end_idx, duration) window whose ends sit on a segment
    boundary preceded/followed by a pause >= pause_threshold_s (or the very
    start/end of the transcript), with duration in [min_duration, max_duration].
    """
    n = len(segments)
    if n == 0:
        return []
    gaps = [segments[i + 1]["start"] - segments[i]["end"] for i in range(n - 1)]
    starts = [i for i in range(n) if i == 0 or gaps[i - 1] >= pause_threshold_s]
    ends = [j for j in range(n) if j == n - 1 or gaps[j] >= pause_threshold_s]

    windows: list[tuple[int, int, float]] = []
    for start in starts:
        for end in ends:
            if end < start:
                continue
            duration = segments[end]["end"] - segments[start]["start"]
            if duration < min_duration:
                continue
            if duration > max_duration:
                # `ends` is ascending and later ends only widen the window, so
                # no later end can satisfy the upper bound either.
                break
            windows.append((start, end, duration))
    return windows


def _score_candidate(
    text: str, duration: float, keywords: list[str], filler_words: list[str], median_rate: float
) -> tuple[float, dict]:
    keyword_hits = sum(text.count(kw) for kw in keywords) if keywords else 0
    keyword_density = keyword_hits / duration if duration > 0 else 0.0
    question_count = sum(text.count(ch) for ch in _QUESTION_CHARS)
    number_count = len(_NUMBER_RE.findall(text))
    entity_like_count = len(_CAPITALIZED_RE.findall(text)) + len(_QUOTED_RE.findall(text))
    speech_rate_cps = len(text) / duration if duration > 0 else 0.0
    speech_rate_above_median = speech_rate_cps > median_rate
    filler_hits = sum(text.count(fw) for fw in filler_words) if filler_words else 0
    filler_density = filler_hits / duration if duration > 0 else 0.0

    score = (
        keyword_density * WEIGHT_KEYWORD
        + question_count * WEIGHT_QUESTION
        + number_count * WEIGHT_NUMBER
        + entity_like_count * WEIGHT_ENTITY
        + (WEIGHT_SPEECH_RATE if speech_rate_above_median else 0.0)
        - filler_density * WEIGHT_FILLER_PENALTY
    )
    components = {
        "keyword_hits": keyword_hits,
        "keyword_density": keyword_density,
        "question_count": question_count,
        "number_count": number_count,
        "entity_like_count": entity_like_count,
        "speech_rate_cps": speech_rate_cps,
        "speech_rate_above_median": speech_rate_above_median,
        "filler_hits": filler_hits,
        "filler_density": filler_density,
    }
    return score, components


def _select_top(scored: list[dict], min_count: int = MIN_CANDIDATES, max_count: int = MAX_CANDIDATES) -> list[dict]:
    """Greedily keep the highest-scoring, non-overlapping candidates (<= max_count).

    `min_count` documents the target from the spec; when fewer non-overlapping
    windows exist, whatever fits is returned rather than forcing overlap.
    """
    ranked = sorted(scored, key=lambda c: c["score"], reverse=True)
    selected: list[dict] = []
    for cand in ranked:
        if len(selected) >= max_count:
            break
        if any(cand["start"] < s["end"] and s["start"] < cand["end"] for s in selected):
            continue
        selected.append(cand)
    selected.sort(key=lambda c: c["start"])
    for idx, cand in enumerate(selected, start=1):
        cand["id"] = f"clip-{idx:04d}"
    return selected


def build_candidates(transcript: dict, config: AppConfig | None = None) -> list[dict]:
    """Score every valid window and return the top candidates (chronological order)."""
    config = config or AppConfig()
    clips_cfg = config.clips or ClipsConfig()
    segments = transcript["segments"]
    if not segments:
        return []

    windows = generate_windows(segments, clips_cfg.pause_threshold_s, clips_cfg.min_duration, clips_cfg.max_duration)
    if not windows:
        return []

    rates = [len(seg["text"]) / max(seg["end"] - seg["start"], 1e-6) for seg in segments]
    median_rate = statistics.median(rates)
    keywords = clips_cfg.keywords or []
    filler_words = config.filler_words or list(DEFAULT_FILLER_WORDS)

    scored: list[dict] = []
    for start_idx, end_idx, duration in windows:
        window_segments = segments[start_idx : end_idx + 1]
        text = "".join(seg["text"] for seg in window_segments)
        start_time = segments[start_idx]["start"]
        end_time = segments[end_idx]["end"]
        score, components = _score_candidate(text, duration, keywords, filler_words, median_rate)
        scored.append(
            {
                "start": start_time,
                "end": end_time,
                "duration": duration,
                "text": text,
                "score": score,
                "score_components": components,
            }
        )
    return _select_top(scored)


def _extract_json_array(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array found in LLM response")
    return text[start : end + 1]


def _call_llm_rerank(candidates: list[dict], api_key: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    items = [
        {
            "id": c["id"],
            "local_score": round(c["score"], 3),
            "duration_s": round(c["duration"], 1),
            "text": c["text"][:600],
        }
        for c in candidates
    ]
    prompt = (
        "You are ranking podcast transcript excerpts as candidates for short "
        "social-media clips. Score each candidate from 0 to 100 on how compelling "
        "it would be as a standalone short clip (hook, clarity, self-containedness), "
        "independent of the given local_score. Return ONLY a JSON array like "
        '[{"id": "clip-0001", "llm_score": 87, "reason": "..."}], one entry per '
        "candidate, no prose before or after it.\n\n" + json.dumps(items, ensure_ascii=False)
    )
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    ranking = json.loads(_extract_json_array(text))
    by_id = {entry["id"]: entry for entry in ranking if "id" in entry}

    for c in candidates:
        entry = by_id.get(c["id"])
        if entry is not None:
            c["rerank"] = {"model": LLM_MODEL, "llm_score": entry.get("llm_score"), "reason": entry.get("reason", "")}

    candidates.sort(key=lambda c: c["rerank"]["llm_score"] if c.get("rerank") else c["score"], reverse=True)
    candidates.sort(key=lambda c: c["start"])  # keep clips.json chronological
    return candidates


def rerank_with_llm(candidates: list[dict], config: AppConfig | None = None) -> list[dict]:
    """Re-rank with Claude when ANTHROPIC_API_KEY is set; otherwise (or on any
    failure) return the local-scorer order unchanged so the command still succeeds.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not candidates:
        return candidates
    try:
        return _call_llm_rerank(candidates, api_key)
    except Exception as exc:  # fail open: LLM re-rank is a bonus, not a dependency
        for c in candidates:
            c["rerank"] = {"model": LLM_MODEL, "error": str(exc)}
        return candidates


def write_clips_json(
    candidates: list[dict],
    source: dict,
    transcript_record: dict,
    keywords: list[str],
    out_path: Path,
) -> None:
    data = {
        "schema": CLIPS_SCHEMA_ID,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "transcript": transcript_record,
        "profile": {"keywords": keywords},
        "candidates": candidates,
    }
    Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_clip_items(existing_items: list[PlanItem], candidates: list[dict]) -> list[PlanItem]:
    """Replace any existing 'clip' items with fresh (disabled) proposals from `candidates`.

    clips.json is regenerated wholesale on every run, so the plan's clip items
    just mirror it; unlike filler proposals there is no human-toggled state to
    preserve (clip items are always enabled=false, see audit.py).
    """
    non_clip = [it for it in existing_items if it.kind != "clip"]
    new_items = [
        PlanItem(
            id=c["id"],
            kind="clip",
            start=c["start"],
            end=c["end"],
            reason=f"clip candidate score={c['score']:.2f}",
            enabled=False,
        )
        for c in candidates
    ]
    return sorted(non_clip + new_items, key=lambda it: it.start)


def render_clip(audio_path: Path, start: float, end: float, output_path: Path, config: AppConfig | None = None) -> Path:
    """Cut [start, end] from audio_path to an MP3 with 100ms fades and loudnorm to config.loudness_target_i."""
    config = config or AppConfig()
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end - start
    fade_out_start = max(0.0, duration - CLIP_FADE_S)
    trim_filter = (
        f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={CLIP_FADE_S:g},afade=t=out:st={fade_out_start:.6f}:d={CLIP_FADE_S:g}"
    )
    with tempfile.TemporaryDirectory(prefix="podcast-autopilot-clip-") as temp:
        trimmed = Path(temp) / "trimmed.wav"
        run_ffmpeg(["-i", str(audio_path), "-af", trim_filter, "-c:a", "pcm_f32le", str(trimmed)], config)

        measured = measure_loudness(trimmed, config)
        loudnorm = (
            f"loudnorm=I={config.loudness_target_i:g}:TP={config.loudness_target_tp:g}:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"offset={measured.get('target_offset', 0)}:linear=true:print_format=summary"
        )
        run_ffmpeg(
            [
                "-i", str(trimmed), "-af", loudnorm,
                "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
                str(output_path),
            ],
            config,
        )
    return output_path


def write_clip_srt(segments: list[dict], start: float, end: float, path: Path) -> None:
    """Sidecar .srt for a clip window, with every timestamp rebased so the window starts at 0."""
    lines: list[str] = []
    idx = 1
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        clipped_start = max(seg["start"], start) - start
        clipped_end = min(seg["end"], end) - start
        if clipped_end <= clipped_start:
            continue
        lines.append(str(idx))
        lines.append(f"{_format_srt_timestamp(clipped_start)} --> {_format_srt_timestamp(clipped_end)}")
        lines.append(seg["text"])
        lines.append("")
        idx += 1
    Path(path).write_text("\n".join(lines), encoding="utf-8")
