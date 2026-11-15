// Honest stand-in for screens that are not built yet (milestones M3/M4). Removed as each lands.
export function mountPlaceholder(root, { title, line }) {
  root.innerHTML = `<div class="card"><div class="centerstate"><h2>${title}</h2><p>${line}</p></div></div>`;
  return { update() {}, resize() {} };
}
