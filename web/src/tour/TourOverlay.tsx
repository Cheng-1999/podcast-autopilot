import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTourOptional } from "./context";
import { useLocale } from "../i18n";
import { computePanelPosition, computeSpotlightRect, type PanelPosition, type Rect } from "./geometry";
import { hasExceededAnchorAttempts, nextFocusIndex } from "./engine";

const POLL_INTERVAL_MS = 80;
const OVERLAY_Z = 2000;

function rectFromElement(el: Element): Rect {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

/** Renders the current tour step as a spotlight + copy panel. Lives outside
 * the normal page flow (mounted once in App) so it can float above any
 * route. Finds its target by querying `[data-tour="<step.anchor>"]` -- pages
 * never need to know the tour exists, they just carry stable anchors. */
export const TourOverlay: React.FC = () => {
  const tour = useTourOptional();
  const { t } = useLocale();
  const panelRef = useRef<HTMLDivElement>(null);
  const [anchorRect, setAnchorRect] = useState<Rect | null>(null);
  const [panelPos, setPanelPos] = useState<PanelPosition | null>(null);
  const lastFocusedStepIdRef = useRef<string | null>(null);

  const step = tour?.isActive ? tour.step : null;
  const isRouteReady = tour?.isRouteReady ?? false;
  const next = tour?.next;
  const back = tour?.back;
  const skip = tour?.skip;
  const stepIndex = tour?.stepIndex ?? 0;
  const totalSteps = tour?.totalSteps ?? 0;

  // Locate (and keep tracking) the current step's anchor element. Some
  // anchors depend on data the page hasn't finished rendering yet, so this
  // polls briefly before giving up and skipping to the next step.
  useEffect(() => {
    setPanelPos(null);
    if (!step || !isRouteReady) {
      setAnchorRect(null);
      return;
    }
    let attempts = 0;
    let cancelled = false;
    const measure = (): boolean => {
      const el = document.querySelector(`[data-tour="${step.anchor}"]`);
      if (el) {
        setAnchorRect(rectFromElement(el));
        return true;
      }
      return false;
    };
    if (!measure()) setAnchorRect(null);
    const interval = window.setInterval(() => {
      if (cancelled) return;
      if (!measure()) {
        attempts += 1;
        if (hasExceededAnchorAttempts(attempts)) {
          // Stop this interval immediately: React may not commit the
          // effect cleanup (which re-runs for the next step) until after
          // the current timer flush, and without this guard a single
          // large time jump would fire several more ticks against this
          // same stale step, calling next() once per tick.
          cancelled = true;
          window.clearInterval(interval);
          next?.();
        }
      }
    }, POLL_INTERVAL_MS);
    window.addEventListener("resize", measure);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("resize", measure);
    };
  }, [step, isRouteReady, next]);

  // Position the copy panel relative to the anchor once both are known.
  useLayoutEffect(() => {
    if (!anchorRect || !step || !panelRef.current) {
      return;
    }
    const rect = panelRef.current.getBoundingClientRect();
    setPanelPos(
      computePanelPosition(
        anchorRect,
        step.placement,
        { width: rect.width, height: rect.height },
        { width: window.innerWidth, height: window.innerHeight }
      )
    );
  }, [anchorRect, step]);

  // Focus the panel once per step so screen readers announce it and
  // keyboard users land somewhere sensible; not on every re-measure.
  useEffect(() => {
    if (panelPos && step && lastFocusedStepIdRef.current !== step.id) {
      panelRef.current?.focus();
      lastFocusedStepIdRef.current = step.id;
    }
  }, [panelPos, step]);

  // Escape dismisses the tour regardless of where focus currently is --
  // the overlay deliberately leaves the spotlighted control interactive,
  // so focus may be on the page rather than the panel.
  useEffect(() => {
    if (!step) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        skip?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [step, skip]);

  const handlePanelKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const focusables = panelRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
    if (!focusables || focusables.length === 0) return;
    const list = Array.from(focusables);
    const current = list.indexOf(document.activeElement as HTMLButtonElement);
    const idx =
      current === -1
        ? e.shiftKey
          ? list.length - 1
          : 0
        : nextFocusIndex(current, list.length, e.shiftKey ? -1 : 1);
    e.preventDefault();
    list[idx]?.focus();
  };

  if (!step) return null;

  const spotlight = anchorRect ? computeSpotlightRect(anchorRect) : null;
  const isLastStep = stepIndex + 1 >= totalSteps;

  const stripBase: React.CSSProperties = {
    position: "fixed",
    backgroundColor: "rgba(4, 6, 10, 0.6)",
    zIndex: OVERLAY_Z,
  };

  return (
    <>
      {spotlight && (
        <>
          <div style={{ ...stripBase, top: 0, left: 0, right: 0, height: Math.max(0, spotlight.top) }} />
          <div
            style={{
              ...stripBase,
              top: spotlight.top + spotlight.height,
              left: 0,
              right: 0,
              bottom: 0,
            }}
          />
          <div
            style={{
              ...stripBase,
              top: spotlight.top,
              left: 0,
              width: Math.max(0, spotlight.left),
              height: spotlight.height,
            }}
          />
          <div
            style={{
              ...stripBase,
              top: spotlight.top,
              left: spotlight.left + spotlight.width,
              right: 0,
              height: spotlight.height,
            }}
          />
          <div
            data-testid="tour-spotlight"
            style={{
              position: "fixed",
              top: spotlight.top,
              left: spotlight.left,
              width: spotlight.width,
              height: spotlight.height,
              borderRadius: "var(--radius-max)",
              boxShadow: "0 0 0 2px var(--semantic-blue)",
              pointerEvents: "none",
              zIndex: OVERLAY_Z,
            }}
          />
        </>
      )}

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="false"
        aria-labelledby="tour-panel-title"
        aria-describedby="tour-panel-body"
        tabIndex={-1}
        onKeyDown={handlePanelKeyDown}
        style={{
          position: "fixed",
          top: panelPos ? panelPos.top : -9999,
          left: panelPos ? panelPos.left : -9999,
          visibility: panelPos ? "visible" : "hidden",
          width: "300px",
          maxWidth: "calc(100vw - 24px)",
          backgroundColor: "var(--surface-elevated)",
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          padding: "14px 16px",
          boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          zIndex: OVERLAY_Z + 1,
          display: "flex",
          flexDirection: "column",
          gap: "10px",
        }}
      >
        <div
          id="tour-panel-title"
          style={{ fontSize: "var(--font-size-sm)", fontWeight: 600, color: "var(--text-primary)" }}
        >
          {t(step.titleKey)}
        </div>
        <div id="tour-panel-body" style={{ fontSize: "var(--font-size-sm)", color: "var(--text-muted)", lineHeight: 1.5 }}>
          {t(step.bodyKey)}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            {t("tour.progress", { current: stepIndex + 1, total: totalSteps })}
          </span>
          <div style={{ display: "flex", gap: "6px" }}>
            <button type="button" className="dense-btn" onClick={() => skip?.()}>
              {t("tour.skip")}
            </button>
            <button type="button" className="dense-btn" disabled={stepIndex === 0} onClick={() => back?.()}>
              {t("tour.back")}
            </button>
            <button type="button" className="dense-btn primary" onClick={() => next?.()}>
              {isLastStep ? t("tour.finish") : t("tour.next")}
            </button>
          </div>
        </div>
      </div>
    </>
  );
};
