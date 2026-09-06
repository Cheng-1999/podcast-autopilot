from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, DEFAULT_FILLER_WORDS, DEFAULT_MODELS_DIR
from .plan import PlanItem

TRANSCRIPT_SCHEMA_ID = "podcast-autopilot.transcript/v1"

# Traditional Chinese, full-width punctuation: faster-whisper's "zh" language
# tag tends to drift toward Simplified output regardless of this prompt, so
# it is a nudge, not a guarantee -- the real fix is the opencc s2twp pass
# applied to every segment/word after transcription.
INITIAL_PROMPT_ZH_TW = "這是一段繁體中文的Podcast逐字稿，請使用正體中文與全形標點符號，例如：「」、，。！？"

_MODEL_CACHE: dict[tuple[str, str], object] = {}


@dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


def _load_model(model_size: str, compute_type: str = "int8", cpu_threads: int | None = None):
    key = (model_size, compute_type)
    if key not in _MODEL_CACHE:
        # huggingface_hub lays the model cache out with symlinks; on Windows
        # without Developer Mode / SeCreateSymbolicLinkPrivilege it warns, then
        # still fails half-way through a download with WinError 1314 (seen on a
        # fresh clone). Plain file copies in tools/models/ are all we need.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from faster_whisper import WhisperModel

        if cpu_threads is None:
            cpu_count = os.cpu_count() or 4
            cpu_threads = min(8, max(2, cpu_count))

        DEFAULT_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        _MODEL_CACHE[key] = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            download_root=str(DEFAULT_MODELS_DIR),
        )
    return _MODEL_CACHE[key]


def _count_changed_chars(before: str, after: str) -> int:
    """Rough diff count for the opencc s2twp post-pass log line, not a real alignment."""
    changed = sum(1 for a, b in zip(before, after) if a != b)
    changed += abs(len(before) - len(after))
    return changed


def transcribe_audio(
    audio_path: Path,
    model_size: str = "small",
    config: AppConfig | None = None,
    compute_type: str = "int8",
    beam_size: int = 1,
) -> dict:
    """Transcribe audio to zh-TW with faster-whisper (CTranslate2, CPU, int8).

    word_timestamps and vad_filter are always on. Whisper's raw "zh" output
    leans Simplified, so opencc s2twp is applied as a post-pass over every
    segment and word; the number of characters it changed is logged in the
    returned dict under "opencc_chars_changed".
    """
    import opencc

    audio_path = Path(audio_path)
    model = _load_model(model_size, compute_type)

    raw_segments, info = model.transcribe(
        str(audio_path),
        language="zh",
        initial_prompt=INITIAL_PROMPT_ZH_TW,
        word_timestamps=True,
        vad_filter=True,
        beam_size=beam_size,
    )

    converter = opencc.OpenCC("s2twp")

    segments: list[Segment] = []
    before_parts: list[str] = []
    after_parts: list[str] = []
    for idx, seg in enumerate(raw_segments):
        raw_text = seg.text.strip()
        text = converter.convert(raw_text)
        before_parts.append(raw_text)
        after_parts.append(text)
        words = [
            Word(
                word=converter.convert(w.word.strip()),
                start=w.start,
                end=w.end,
                probability=w.probability,
            )
            for w in (seg.words or [])
        ]
        segments.append(Segment(id=idx, start=seg.start, end=seg.end, text=text, words=words))

    chars_changed = _count_changed_chars("".join(before_parts), "".join(after_parts))

    return {
        "schema": TRANSCRIPT_SCHEMA_ID,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(audio_path)},
        "model": {"size": model_size, "compute_type": compute_type, "device": "cpu"},
        "language": info.language,
        "language_probability": info.language_probability,
        "opencc_chars_changed": chars_changed,
        "segments": segments,
    }


def save_transcript(data: dict, path: Path) -> None:
    plain = {**data, "segments": [asdict(s) for s in data["segments"]]}
    Path(path).write_text(json.dumps(plain, indent=2, ensure_ascii=False), encoding="utf-8")


def load_transcript(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def words_from_transcript(data: dict) -> list[Word]:
    """Flatten every segment's words into one time-ordered list (already absolute timestamps)."""
    words: list[Word] = []
    for seg in data["segments"]:
        for w in seg["words"]:
            words.append(Word(word=w["word"], start=w["start"], end=w["end"], probability=w["probability"]))
    return words


def _format_srt_timestamp(seconds: float) -> str:
    ms_total = max(0, round(seconds * 1000))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(segments: list[Segment], path: Path) -> None:
    lines: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_format_srt_timestamp(seg.start)} --> {_format_srt_timestamp(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _format_mm_ss(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def write_markdown(segments: list[Segment], path: Path) -> None:
    paragraphs = [f"[{_format_mm_ss(seg.start)}] {seg.text}" for seg in segments]
    Path(path).write_text("\n\n".join(paragraphs) + ("\n" if paragraphs else ""), encoding="utf-8")


def detect_fillers(
    words: list[Word],
    filler_words: list[str] | None = None,
    pause_threshold_s: float = 0.2,
    min_probability: float = 0.5,
) -> list[dict]:
    """Flag filler-word candidates that are isolated by pauses on both sides.

    A word only qualifies when: its stripped text is one of `filler_words`,
    its probability is above `min_probability`, and the gap to the previous
    word's end and to the next word's start are both greater than
    `pause_threshold_s`. The first and last word of the list have no
    neighbour on one side, so a pause there cannot be confirmed and they are
    never proposed (fail closed: a proposal must be backed by two measured
    pauses).
    """
    filler_set = set(filler_words) if filler_words is not None else set(DEFAULT_FILLER_WORDS)
    candidates: list[dict] = []
    for i in range(1, len(words) - 1):
        w = words[i]
        token = w.word.strip()
        if token not in filler_set:
            continue
        if w.probability <= min_probability:
            continue
        prev_gap = w.start - words[i - 1].end
        next_gap = words[i + 1].start - w.end
        if prev_gap <= pause_threshold_s or next_gap <= pause_threshold_s:
            continue
        candidates.append({"word": token, "start": w.start, "end": w.end, "probability": w.probability})
    return candidates


FILLER_MATCH_TOLERANCE_S = 0.001


def _filler_index(item_id: str) -> int:
    try:
        return int(item_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def merge_filler_items(
    existing_items: list[PlanItem],
    candidates: list[dict],
    keep_spans: list[tuple[float, float]] | None = None,
) -> list[PlanItem]:
    """Return the plan's item list with filler proposals replaced by `candidates`, idempotently.

    - A candidate whose [start, end] matches an existing filler item (within
      FILLER_MATCH_TOLERANCE_S) keeps that item as-is, including its id and
      any `enabled=true` a human already set.
    - Existing disabled filler proposals that no longer match any candidate
      are dropped (they were only ever proposals).
    - Existing *enabled* filler items that no longer match are kept: a human
      decision is never silently discarded by re-running detection.
    - Remaining candidates become new disabled proposals numbered after the
      highest surviving filler index.
    Running this twice with the same transcript yields the same item list,
    so plan-fillers never accumulates duplicate (overlapping) proposals.
    """
    if keep_spans is not None:
        candidates = [
            c for c in candidates
            if any(ks <= c["start"] and c["end"] <= ke for ks, ke in keep_spans)
        ]

    non_filler = [it for it in existing_items if it.kind != "filler"]
    existing_fillers = [it for it in existing_items if it.kind == "filler"]

    kept: list[PlanItem] = []
    unmatched: list[dict] = []
    matched_ids: set[str] = set()
    for c in candidates:
        match = next(
            (
                it
                for it in existing_fillers
                if it.id not in matched_ids
                and abs(it.start - c["start"]) <= FILLER_MATCH_TOLERANCE_S
                and abs(it.end - c["end"]) <= FILLER_MATCH_TOLERANCE_S
            ),
            None,
        )
        if match is not None:
            matched_ids.add(match.id)
            kept.append(match)
        else:
            unmatched.append(c)

    for it in existing_fillers:
        if it.id not in matched_ids and it.enabled:
            kept.append(it)

    if keep_spans is not None:
        kept = [
            it for it in kept
            if any(ks <= it.start and it.end <= ke for ks, ke in keep_spans)
        ]

    next_index = max((_filler_index(it.id) for it in kept), default=0) + 1
    new_items = filler_plan_items(unmatched, start_index=next_index)
    return sorted(non_filler + kept + new_items, key=lambda it: it.start)


def filler_plan_items(candidates: list[dict], start_index: int = 1) -> list[PlanItem]:
    """Build disabled 'filler' PlanItems (proposals only) from detect_fillers() output."""
    items = []
    for offset, c in enumerate(candidates):
        idx = start_index + offset
        items.append(
            PlanItem(
                id=f"filler-{idx:04d}",
                kind="filler",
                start=c["start"],
                end=c["end"],
                reason=f"filler:{c['word']} p={c['probability']:.2f}",
                enabled=False,
            )
        )
    return items
