export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export const SPOTLIGHT_PADDING = 8;
export const PANEL_GAP = 12;

/** The highlighted region around an anchor element, padded so the spotlight
 * reads as a halo rather than an exact outline. */
export function computeSpotlightRect(anchor: Rect, padding: number = SPOTLIGHT_PADDING): Rect {
  return {
    top: anchor.top - padding,
    left: anchor.left - padding,
    width: anchor.width + padding * 2,
    height: anchor.height + padding * 2,
  };
}

export type Placement = "top" | "bottom" | "left" | "right";

export interface PanelPosition {
  top: number;
  left: number;
  placement: Placement;
}

/** Positions the copy panel next to the anchor on the requested side, falling
 * back to whichever side actually has room, then clamps to the viewport so
 * the panel never renders partly off-screen on small windows. */
export function computePanelPosition(
  anchor: Rect,
  placement: Placement,
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  gap: number = PANEL_GAP
): PanelPosition {
  const fits = (p: Placement): boolean => {
    switch (p) {
      case "top":
        return anchor.top - gap - panel.height >= 0;
      case "bottom":
        return anchor.top + anchor.height + gap + panel.height <= viewport.height;
      case "left":
        return anchor.left - gap - panel.width >= 0;
      case "right":
        return anchor.left + anchor.width + gap + panel.width <= viewport.width;
    }
  };

  const candidates: Placement[] = [placement, "bottom", "top", "right", "left"];
  const resolved = candidates.find(fits) ?? placement;

  let top: number;
  let left: number;
  switch (resolved) {
    case "top":
      top = anchor.top - gap - panel.height;
      left = anchor.left + anchor.width / 2 - panel.width / 2;
      break;
    case "bottom":
      top = anchor.top + anchor.height + gap;
      left = anchor.left + anchor.width / 2 - panel.width / 2;
      break;
    case "left":
      top = anchor.top + anchor.height / 2 - panel.height / 2;
      left = anchor.left - gap - panel.width;
      break;
    case "right":
      top = anchor.top + anchor.height / 2 - panel.height / 2;
      left = anchor.left + anchor.width + gap;
      break;
  }

  left = Math.max(gap, Math.min(left, viewport.width - panel.width - gap));
  top = Math.max(gap, Math.min(top, viewport.height - panel.height - gap));

  return { top, left, placement: resolved };
}
