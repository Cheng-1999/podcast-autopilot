import React, { useCallback, useEffect, useRef, useState } from "react";
import type { PlanItem } from "../api/types";
import { resampleForView } from "../lib/waveform";

interface WaveformProps {
  peaks: number[][];
  duration: number;
  items: PlanItem[];
  selectedItemId: string | null;
  currentTime: number;
  onSeek: (time: number) => void;
  onSelectItem: (id: string) => void;
}

const KIND_COLOR: Record<string, string> = {
  cut: "229, 72, 77",
  filler: "245, 165, 36",
  clip: "76, 141, 255",
};

const MIN_VIEW_SPAN = 1;

export const Waveform: React.FC<WaveformProps> = ({
  peaks,
  duration,
  items,
  selectedItemId,
  currentTime,
  onSeek,
  onSelectItem,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<{ start: number; end: number }>({ start: 0, end: duration || 1 });
  const draggingRef = useRef(false);
  const lastSelectedRef = useRef<string | null>(null);

  // Reset the view window when a new part loads.
  useEffect(() => {
    setView({ start: 0, end: duration || 1 });
  }, [duration]);

  // Scroll the view to bring the selected item into frame, preserving zoom span.
  useEffect(() => {
    if (!selectedItemId || selectedItemId === lastSelectedRef.current) return;
    lastSelectedRef.current = selectedItemId;
    const item = items.find((it) => it.id === selectedItemId);
    if (!item) return;
    setView((prev) => {
      const span = prev.end - prev.start;
      if (item.start >= prev.start && item.end <= prev.end) return prev;
      const center = (item.start + item.end) / 2;
      let start = center - span / 2;
      let end = center + span / 2;
      if (start < 0) {
        end -= start;
        start = 0;
      }
      if (end > duration) {
        start -= end - duration;
        end = duration;
      }
      return { start: Math.max(0, start), end: Math.min(duration, end) };
    });
  }, [selectedItemId, items, duration]);

  const timeAtX = useCallback(
    (clientX: number): number => {
      const canvas = canvasRef.current;
      if (!canvas) return 0;
      const rect = canvas.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      return view.start + frac * (view.end - view.start);
    },
    [view]
  );

  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLCanvasElement>) => {
      e.preventDefault();
      const canvas = canvasRef.current;
      if (!canvas || duration <= 0) return;
      const rect = canvas.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const pivot = view.start + frac * (view.end - view.start);
      const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      let span = (view.end - view.start) * factor;
      span = Math.max(MIN_VIEW_SPAN, Math.min(duration, span));
      let start = pivot - frac * span;
      let end = start + span;
      if (start < 0) {
        end -= start;
        start = 0;
      }
      if (end > duration) {
        start -= end - duration;
        end = duration;
      }
      setView({ start: Math.max(0, start), end: Math.min(duration, end) });
    },
    [view, duration]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      draggingRef.current = true;
      onSeek(timeAtX(e.clientX));
    },
    [timeAtX, onSeek]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!draggingRef.current) return;
      onSeek(timeAtX(e.clientX));
    },
    [timeAtX, onSeek]
  );

  const stopDragging = useCallback(() => {
    draggingRef.current = false;
  }, []);

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const t = timeAtX(e.clientX);
      const hit = items.find((it) => t >= it.start && t <= it.end);
      if (hit) onSelectItem(hit.id);
    },
    [timeAtX, items, onSelectItem]
  );

  // Draw.
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const dpr = window.devicePixelRatio || 1;
    const widthPx = container.clientWidth || 800;
    const heightPx = 140;
    canvas.width = widthPx * dpr;
    canvas.height = heightPx * dpr;
    canvas.style.width = `${widthPx}px`;
    canvas.style.height = `${heightPx}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, widthPx, heightPx);

    ctx.fillStyle = "#0F1216";
    ctx.fillRect(0, 0, widthPx, heightPx);

    const midY = heightPx / 2;
    const span = view.end - view.start || 1;

    if (peaks.length > 0 && duration > 0) {
      const cols = resampleForView(peaks, duration, view.start, view.end, widthPx);
      ctx.fillStyle = "#4C8DFF";
      for (let x = 0; x < cols.length; x++) {
        const [min, max] = cols[x];
        const yMin = midY - (max / 32768) * midY;
        const yMax = midY - (min / 32768) * midY;
        ctx.fillRect(x, yMin, 1, Math.max(1, yMax - yMin));
      }
    }

    // Plan item overlay bands.
    for (const item of items) {
      const x0 = ((item.start - view.start) / span) * widthPx;
      const x1 = ((item.end - view.start) / span) * widthPx;
      if (x1 < 0 || x0 > widthPx) continue;
      const color = KIND_COLOR[item.kind] ?? "139, 147, 161";
      const hollow = !item.enabled;
      const isClip = item.kind === "clip";
      const w = Math.max(1, x1 - x0);

      if (!hollow && !isClip) {
        ctx.fillStyle = `rgba(${color}, 0.6)`;
        ctx.fillRect(x0, 0, w, heightPx);
      } else {
        ctx.strokeStyle = hollow ? `rgba(${color}, 0.7)` : `rgba(${color}, 0.9)`;
        ctx.lineWidth = 1;
        ctx.setLineDash(hollow ? [3, 2] : []);
        ctx.strokeRect(x0 + 0.5, 0.5, Math.max(1, w - 1), heightPx - 1);
        ctx.setLineDash([]);
      }

      if (item.id === selectedItemId) {
        ctx.strokeStyle = "#DDE1E6";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x0, 0, w, heightPx);
      }
    }

    // Playhead.
    if (currentTime >= view.start && currentTime <= view.end) {
      const x = ((currentTime - view.start) / span) * widthPx;
      ctx.strokeStyle = "#DDE1E6";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, heightPx);
      ctx.stroke();
    }
  }, [peaks, duration, view, items, selectedItemId, currentTime]);

  return (
    <div ref={containerRef} style={{ width: "100%" }}>
      <canvas
        ref={canvasRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={stopDragging}
        onMouseLeave={stopDragging}
        onDoubleClick={handleDoubleClick}
        style={{ display: "block", cursor: "pointer", borderRadius: "var(--radius-max)" }}
      />
    </div>
  );
};
