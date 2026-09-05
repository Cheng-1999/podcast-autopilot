/** Resample [min,max] peak buckets (covering the full source duration) down to
 * `widthPx` columns spanning the visible [viewStart, viewEnd] window. */
export function resampleForView(
  peaks: number[][],
  duration: number,
  viewStart: number,
  viewEnd: number,
  widthPx: number
): number[][] {
  const bucketCount = peaks.length;
  if (bucketCount === 0 || widthPx <= 0 || duration <= 0) {
    return Array.from({ length: Math.max(widthPx, 0) }, () => [0, 0]);
  }
  const out: number[][] = new Array(widthPx);
  const secondsPerBucket = duration / bucketCount;
  for (let x = 0; x < widthPx; x++) {
    const t0 = viewStart + (x / widthPx) * (viewEnd - viewStart);
    const t1 = viewStart + ((x + 1) / widthPx) * (viewEnd - viewStart);
    let b0 = Math.floor(t0 / secondsPerBucket);
    let b1 = Math.ceil(t1 / secondsPerBucket) - 1;
    b0 = Math.max(0, Math.min(bucketCount - 1, b0));
    b1 = Math.max(0, Math.min(bucketCount - 1, b1));
    if (b1 < b0) b1 = b0;
    let min = 32767;
    let max = -32768;
    for (let b = b0; b <= b1; b++) {
      const [bMin, bMax] = peaks[b];
      if (bMin < min) min = bMin;
      if (bMax > max) max = bMax;
    }
    out[x] = [min, max];
  }
  return out;
}
