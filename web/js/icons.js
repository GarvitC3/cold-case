export const ICONS = {

  person: '<circle cx="12" cy="4.6" r="2.1"/><path d="M12 7.6v6.2M12 13.8l-3.2 6.4M12 13.8l3.2 6.4M12 9.4l-4 3.1M12 9.4l4 3.1"/>',
  snowmobile: '<path d="M2.5 17.5h6.5M9 17.5l2.2-5.8h4.6l3 3.2h2.2"/><path d="M11.2 11.7L9.6 8.6h-2.8"/><path d="M11.5 18.2h9a1.7 1.7 0 0 1 0 3.4h-9a1.7 1.7 0 0 1 0-3.4z"/>',
  car: '<path d="M3 16.5v-4l2.2-4.6h13.6L21 12.5v4z"/><path d="M5.2 12.5h13.6"/><circle cx="7.4" cy="17.4" r="1.9"/><circle cx="16.6" cy="17.4" r="1.9"/>',
  truck: '<path d="M2.5 17.5V8.5H13v9"/><path d="M13 11.5h4.4l3.6 3.4v2.6"/><circle cx="6.6" cy="18" r="1.9"/><circle cx="17" cy="18" r="1.9"/>',

  now: '<path d="M12 3v18M4.6 7.5l14.8 9M19.4 7.5l-14.8 9"/><path d="M9.6 4.6L12 6.8l2.4-2.2M9.6 19.4L12 17.2l2.4 2.2"/>',
  season: '<path d="M3.5 18.5C6 18 7.5 12 10 11c2.4-1 3.3 4 5.5 3.6C18 14 18.6 8 20.5 6"/><path d="M3.5 21h17"/><path d="M3.5 9.5C6 9.5 8 6 10.5 6.4"/>',
  trend: '<path d="M4 6v12M8 6v12M12 6v12M16 6v12M20 6v12" stroke-width="2.6" opacity=".85"/><path d="M4 12h16" opacity="0"/>',
  thermo: '<path d="M10 14.2V5.4a2 2 0 0 1 4 0v8.8a4 4 0 1 1-4 0z"/>',
};
export function svgIcon(name, cls = '') {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}
