import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchEpisode,
  fetchPlan,
  fetchTranscript,
  fetchPeaks,
  putPlan,
  addManualCut,
  suggestCutsAI,
  runEpisode,
  mediaUrl,
  parseReapplyOptions,
} from "../api/client";
import type { EpisodeDetail, PlanItem, PlanResponse, TranscriptResponse, PeaksResponse, AISuggestedCut } from "../api/types";
import { Waveform } from "../components/Waveform";
import { ItemList } from "../components/ItemList";
import { TranscriptPane } from "../components/TranscriptPane";
import { computeSecondsRemoved, computeEnabledFillerCount, computeSnippetRange } from "../lib/planMath";
import { formatTimeTenths, formatDecimal } from "../lib/format";
import { registerNavigationGuard, confirmNavigation } from "../lib/navigationGuard";
import { useLocale } from "../i18n";

function partStems(episode: EpisodeDetail | undefined): string[] {
  if (!episode) return [];
  if (episode.parts_detail && episode.parts_detail.length > 0) {
    return episode.parts_detail.map((p) => p.stem);
  }
  return (episode.parts || []).map((p) => p.replace(/\.[^/.]+$/, ""));
}

/** Extract the ids referenced by audit_plan-style error strings, e.g.
 * "item filler-99 overlaps with keep-0 [...]". Used to flag offending rows and
 * to show the exact message(s) beside each one. */
function extractErrorsByItemId(errors: string[], knownIds: Set<string>): Map<string, string[]> {
  const hit = new Map<string, string[]>();
  for (const err of errors) {
    for (const id of knownIds) {
      if (err.includes(id)) {
        const existing = hit.get(id) ?? [];
        existing.push(err);
        hit.set(id, existing);
      }
    }
  }
  return hit;
}

export const ReviewPage: React.FC = () => {
  const { t, locale } = useLocale();
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: episode } = useQuery<EpisodeDetail>({
    queryKey: ["episode", id],
    queryFn: () => fetchEpisode(id),
    enabled: Boolean(id),
  });

  const stems = useMemo(() => partStems(episode), [episode]);
  const [activePart, setActivePart] = useState<string>("");

  useEffect(() => {
    if (!activePart && stems.length > 0) setActivePart(stems[0]);
  }, [stems, activePart]);

  const { data: plan } = useQuery<PlanResponse>({
    queryKey: ["plan", id, activePart],
    queryFn: () => fetchPlan(id, activePart),
    enabled: Boolean(id && activePart),
  });

  const { data: transcript } = useQuery<TranscriptResponse>({
    queryKey: ["transcript", id, activePart],
    queryFn: () => fetchTranscript(id, activePart),
    enabled: Boolean(id && activePart),
  });

  const { data: peaksData } = useQuery<PeaksResponse>({
    queryKey: ["peaks", id, activePart],
    queryFn: () => fetchPeaks(id, activePart),
    enabled: Boolean(id && activePart),
  });

  const [localItems, setLocalItems] = useState<PlanItem[]>([]);
  const [baselineItems, setBaselineItems] = useState<PlanItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [pendingCutStart, setPendingCutStart] = useState<number | null>(null);
  const [addingCut, setAddingCut] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState<AISuggestedCut[] | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [acceptingIndex, setAcceptingIndex] = useState<number | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const snippetStopRef = useRef<number | null>(null);

  useEffect(() => {
    if (plan) {
      setLocalItems(plan.items);
      setBaselineItems(plan.items);
      setSelectedItemId(plan.items[0]?.id ?? null);
      setErrors([]);
      setSaveState("idle");
      setPendingCutStart(null);
      setAiSuggestions(null);
      setAiError(null);
    }
  }, [plan]);

  const dirty = useMemo(() => JSON.stringify(localItems) !== JSON.stringify(baselineItems), [
    localItems,
    baselineItems,
  ]);

  const duration = plan?.source.duration ?? 0;
  const secondsRemoved = useMemo(() => computeSecondsRemoved(localItems), [localItems]);
  const fillerCount = useMemo(() => computeEnabledFillerCount(localItems), [localItems]);

  const knownIds = useMemo(() => new Set(localItems.map((it) => it.id)), [localItems]);
  const errorsByItemId = useMemo(() => extractErrorsByItemId(errors, knownIds), [errors, knownIds]);

  const audioSrc = activePart ? mediaUrl(id, `parts/${activePart}/${activePart}.clean.wav`) : "";

  const selectItem = useCallback((itemId: string) => {
    setSelectedItemId(itemId);
  }, []);

  const toggleEnabled = useCallback((itemId: string) => {
    setLocalItems((prev) => prev.map((it) => (it.id === itemId ? { ...it, enabled: !it.enabled } : it)));
  }, []);

  const seek = useCallback((time: number) => {
    snippetStopRef.current = null;
    if (audioRef.current) {
      audioRef.current.currentTime = time;
    }
    setCurrentTime(time);
  }, []);

  const playSnippet = useCallback(() => {
    const item = localItems.find((it) => it.id === selectedItemId);
    const audio = audioRef.current;
    if (!item || !audio) return;
    const { start, end } = computeSnippetRange(item, duration);
    snippetStopRef.current = end;
    audio.currentTime = start;
    audio.play();
  }, [localItems, selectedItemId, duration]);

  const handleTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrentTime(audio.currentTime);
    if (snippetStopRef.current !== null && audio.currentTime >= snippetStopRef.current) {
      audio.pause();
      snippetStopRef.current = null;
    }
  }, []);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      snippetStopRef.current = null;
      audio.play();
    } else {
      audio.pause();
    }
  }, []);

  const markCutStart = useCallback(() => {
    setPendingCutStart(currentTime);
  }, [currentTime]);

  const cancelPendingCut = useCallback(() => {
    setPendingCutStart(null);
  }, []);

  const confirmCut = useCallback(async () => {
    if (pendingCutStart === null || !activePart) return;
    const start = Math.min(pendingCutStart, currentTime);
    const end = Math.max(pendingCutStart, currentTime);
    if (end - start < 0.01) {
      setErrors([t("review.addCutFailed") + " range is too short"]);
      return;
    }
    setAddingCut(true);
    try {
      const result = await addManualCut(id, activePart, { start, end, reason: "manual" });
      if (!result.ok) {
        setErrors((result.errors ?? []).map((e) => `${t("review.addCutFailed")} ${e}`));
        return;
      }
      setPendingCutStart(null);
      setErrors([]);
      await queryClient.invalidateQueries({ queryKey: ["plan", id, activePart] });
      queryClient.invalidateQueries({ queryKey: ["episode", id] });
    } catch (err) {
      setErrors([`${t("review.addCutFailed")} ${(err as Error).message}`]);
    } finally {
      setAddingCut(false);
    }
  }, [pendingCutStart, currentTime, activePart, id, queryClient, t]);

  const requestAiSuggestions = useCallback(async () => {
    if (!activePart) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await suggestCutsAI(id, activePart);
      setAiSuggestions(result.suggestions);
    } catch (err) {
      setAiError((err as Error).message);
      setAiSuggestions(null);
    } finally {
      setAiLoading(false);
    }
  }, [id, activePart]);

  const acceptAiSuggestion = useCallback(
    async (index: number) => {
      const suggestion = aiSuggestions?.[index];
      if (!suggestion || !activePart) return;
      setAcceptingIndex(index);
      try {
        const result = await addManualCut(id, activePart, {
          start: suggestion.start,
          end: suggestion.end,
          reason: suggestion.reason,
        });
        if (!result.ok) {
          setAiError((result.errors ?? []).join("; "));
          return;
        }
        setAiSuggestions((prev) => (prev ? prev.filter((_, i) => i !== index) : prev));
        await queryClient.invalidateQueries({ queryKey: ["plan", id, activePart] });
        queryClient.invalidateQueries({ queryKey: ["episode", id] });
      } catch (err) {
        setAiError((err as Error).message);
      } finally {
        setAcceptingIndex(null);
      }
    },
    [aiSuggestions, activePart, id, queryClient]
  );

  const dismissAiSuggestion = useCallback((index: number) => {
    setAiSuggestions((prev) => (prev ? prev.filter((_, i) => i !== index) : prev));
  }, []);

  const doSave = useCallback(async (): Promise<boolean> => {
    if (!activePart) return false;
    setSaveState("saving");
    try {
      const body = localItems.map((it) => ({ id: it.id, enabled: it.enabled }));
      const result = await putPlan(id, activePart, body);
      if (!result.ok) {
        setErrors(result.errors ?? []);
        setSaveState("error");
        return false;
      }
      setBaselineItems(localItems);
      setErrors([]);
      setSaveState("saved");
      queryClient.invalidateQueries({ queryKey: ["episode", id] });
      return true;
    } catch (err) {
      setErrors([(err as Error).message]);
      setSaveState("error");
      return false;
    }
  }, [id, activePart, localItems, queryClient]);

  const doReapply = useCallback(async () => {
    const saved = await doSave();
    if (!saved) return;
    const { profile, model } = parseReapplyOptions(episode?.reapply_command ?? null);
    try {
      await runEpisode(id, { profile, model });
      queryClient.invalidateQueries({ queryKey: ["episode", id] });
      queryClient.invalidateQueries({ queryKey: ["episodes"] });
      navigate(`/episodes/${id}`, {
        state: {
          reapplyCaption: "重新套用中：僅重跑 audit / apply / assemble（其餘階段使用快取）",
        },
      });
    } catch (err) {
      setErrors([(err as Error).message]);
      setSaveState("error");
    }
  }, [doSave, episode, id, navigate, queryClient]);

  const guardedNavigate = useCallback(
    (to: string) => {
      if (!confirmNavigation()) return;
      navigate(to);
    },
    [navigate]
  );

  useEffect(() => {
    registerNavigationGuard(() =>
      !dirty || window.confirm(t("review.leaveConfirm"))
    );
    return () => registerNavigationGuard(null);
  }, [dirty, t]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if (localItems.length === 0) return;
      const idx = localItems.findIndex((it) => it.id === selectedItemId);

      if (e.key === "j") {
        e.preventDefault();
        const next = localItems[Math.min(localItems.length - 1, idx + 1)];
        if (next) setSelectedItemId(next.id);
      } else if (e.key === "k") {
        e.preventDefault();
        const prev = localItems[Math.max(0, idx - 1)];
        if (prev) setSelectedItemId(prev.id);
      } else if (e.key === " ") {
        e.preventDefault();
        playSnippet();
      } else if (e.key === "e") {
        e.preventDefault();
        if (selectedItemId) toggleEnabled(selectedItemId);
      } else if (e.key === "s") {
        e.preventDefault();
        doSave();
      } else if (e.key === "a") {
        e.preventDefault();
        doReapply();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [localItems, selectedItemId, playSnippet, toggleEnabled, doSave, doReapply]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
          paddingBottom: "8px",
          borderBottom: "var(--border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button type="button" className="dense-btn" onClick={() => guardedNavigate(`/episodes/${id}`)}>
            {t("nav.back")}
          </button>
          <span style={{ color: "var(--text-primary)" }}>{t("detail.review")} — {episode?.title || id}</span>
          {dirty && <span style={{ color: "var(--semantic-amber)", fontSize: "var(--font-size-xs)" }}>{t("review.unsaved")}</span>}
        </div>
        <div style={{ display: "flex", gap: "6px" }}>
          {stems.map((stem) => (
            <button
              key={stem}
              type="button"
              className="dense-btn"
              onClick={() => {
                if (stem === activePart) return;
                if (dirty && !window.confirm(t("review.switchConfirm"))) return;
                setActivePart(stem);
              }}
              style={
                stem === activePart
                  ? { backgroundColor: "var(--surface-elevated)", color: "var(--semantic-blue)", borderColor: "var(--semantic-blue)" }
                  : undefined
              }
            >
              {stem}
            </button>
          ))}
        </div>
      </div>

      {errors.length > 0 && (
        <div
          style={{
            padding: "10px 12px",
            backgroundColor: "rgba(229, 72, 77, 0.1)",
            border: "1px solid rgba(229, 72, 77, 0.3)",
            borderRadius: "var(--radius-max)",
            color: "var(--semantic-red)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "4px" }}>{t("review.failed")}</div>
          <ul style={{ paddingLeft: "18px" }}>
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          backgroundColor: "var(--surface-panel)",
          fontSize: "var(--font-size-sm)",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <div className="mono tabular-nums" style={{ color: "var(--text-primary)" }}>
          {t("review.fillerSummary", { count: fillerCount, seconds: formatDecimal(secondsRemoved, locale, 1), duration: formatTimeTenths(duration, locale) })}
        </div>
        <div style={{ display: "flex", gap: "6px" }}>
          <button type="button" data-testid="save-plan-button" className="dense-btn" disabled={!dirty || saveState === "saving"} onClick={doSave}>
            {t("common.save")} <span className="kbd-hint">s</span>
          </button>
          <button type="button" data-tour="review-reapply" className="dense-btn primary" disabled={saveState === "saving"} onClick={doReapply}>
            {t("review.saveApply")} <span className="kbd-hint">a</span>
          </button>
          {saveState === "saved" && <span style={{ color: "var(--semantic-green)", alignSelf: "center" }}>{t("common.saved")}</span>}
        </div>
      </div>

      <audio
        ref={audioRef}
        src={audioSrc}
        onTimeUpdate={handleTimeUpdate}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        style={{ display: "none" }}
      />

      <div
        data-tour="waveform"
        style={{
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          backgroundColor: "var(--surface-panel)",
          padding: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "0 4px 8px", fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
          <button type="button" className="dense-btn" onClick={togglePlay} disabled={!audioSrc}>
            {isPlaying ? t("review.pause") : t("review.play")}
          </button>
          <span className="mono tabular-nums">
            {formatTimeTenths(currentTime, locale)} / {formatTimeTenths(duration, locale)}
          </span>
          {pendingCutStart === null ? (
            <button type="button" className="dense-btn" onClick={markCutStart} disabled={!audioSrc}>
              {t("review.markCutStart")}
            </button>
          ) : (
            <>
              <span className="mono tabular-nums">
                {t("review.cuttingFrom", { start: formatTimeTenths(pendingCutStart, locale) })}
              </span>
              <button type="button" className="dense-btn primary" onClick={confirmCut} disabled={addingCut}>
                {t("review.confirmCut")}
              </button>
              <button type="button" className="dense-btn" onClick={cancelPendingCut} disabled={addingCut}>
                {t("common.cancel")}
              </button>
            </>
          )}
          <span><span style={{ color: "rgb(229,72,77)" }}>■</span> {t("review.legendCut")}</span>
          <span><span style={{ color: "rgb(245,165,36)" }}>■</span> {t("review.legendFiller")}</span>
          <span><span style={{ color: "rgb(76,141,255)" }}>▢</span> {t("review.legendClip")}</span>
          <span>▢ {t("review.legendDisabled")}</span>
          <span style={{ marginLeft: "auto" }}>{t("review.zoom")}</span>
        </div>
        <Waveform
          peaks={peaksData?.peaks ?? []}
          duration={duration}
          items={localItems}
          selectedItemId={selectedItemId}
          currentTime={currentTime}
          onSeek={seek}
          onSelectItem={selectItem}
        />
      </div>

      <div
        style={{
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          backgroundColor: "var(--surface-panel)",
          padding: "8px 12px",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          fontSize: "var(--font-size-sm)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <button type="button" className="dense-btn" onClick={requestAiSuggestions} disabled={aiLoading || !activePart}>
            {aiLoading ? t("review.aiSuggestLoading") : t("review.aiSuggest")}
          </button>
          {aiError && <span style={{ color: "var(--semantic-red)" }}>{aiError}</span>}
          {aiSuggestions && aiSuggestions.length === 0 && !aiError && (
            <span style={{ color: "var(--text-muted)" }}>{t("review.aiSuggestNone")}</span>
          )}
        </div>
        {aiSuggestions && aiSuggestions.length > 0 && (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "4px" }}>
            {aiSuggestions.map((s, i) => (
              <li key={i} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className="mono tabular-nums">
                  {formatTimeTenths(s.start, locale)}–{formatTimeTenths(s.end, locale)}
                </span>
                <span style={{ color: "var(--text-muted)", flex: 1 }}>{s.reason}</span>
                {!s.valid && <span style={{ color: "var(--semantic-red)" }}>{s.errors.join("; ")}</span>}
                <button
                  type="button"
                  className="dense-btn primary"
                  disabled={!s.valid || acceptingIndex === i}
                  onClick={() => acceptAiSuggestion(i)}
                >
                  {t("review.aiSuggestAccept")}
                </button>
                <button type="button" className="dense-btn" disabled={acceptingIndex === i} onClick={() => dismissAiSuggestion(i)}>
                  {t("review.aiSuggestDismiss")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gridTemplateRows: "minmax(0, 1fr)",
          gap: "12px",
          height: "60vh",
          minHeight: "420px",
        }}
      >
        <TranscriptPane segments={transcript?.segments ?? []} currentTime={currentTime} onSeek={seek} />
        <ItemList
          items={localItems}
          selectedItemId={selectedItemId}
          onSelect={selectItem}
          onToggleEnabled={toggleEnabled}
          errorsByItemId={errorsByItemId}
        />
      </div>
    </div>
  );
};
