let frames = 0, last = performance.now(), slow = 0;
export function startPerf() {
  const root = document.documentElement;
  const tick = (t) => {
    frames++;
    if (t - last >= 1000) {
      const fps = frames * 1000 / (t - last);
      window.__fps = Math.round(fps);
      slow = fps < 30 ? slow + 1 : Math.max(0, slow - 1);
      if (slow >= 3) root.dataset.quality = 'low';
      if (slow === 0 && root.dataset.quality === 'low' && fps > 50) root.dataset.quality = 'high';
      frames = 0; last = t;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
