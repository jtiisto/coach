# Plan: Full Installable PWA

## Current State

The app is **partially PWA-ready**:
- Mobile viewport, theme-color, and Apple meta tags in `public/index.html`
- Offline data persistence via LocalForage/IndexedDB in `public/js/store.js`
- Online/offline detection with auto-sync on reconnect
- Responsive, touch-friendly dark UI
- No-build ES modules architecture (Preact + htm from esm.sh CDN)

**Missing for installability:**
- No `manifest.json`
- No service worker
- No app icons (no favicon, no touch icons, nothing)
- No install prompt handling
- No offline asset caching (only data is offline-capable)

---

## Step 1: App Icons

Create icon assets in `public/icons/`:

| File | Size | Purpose |
|------|------|---------|
| `icon.svg` | scalable | Favicon, maskable base |
| `icon-192.png` | 192x192 | Manifest icon |
| `icon-512.png` | 512x512 | Manifest icon, splash |
| `icon-maskable-192.png` | 192x192 | Android adaptive icon (with safe zone padding) |
| `icon-maskable-512.png` | 512x512 | Android adaptive icon |
| `apple-touch-icon.png` | 180x180 | iOS home screen |

Design: simple glyph (dumbbell or flexed bicep style) on `#1a1a2e` background with `#e94560` accent. Keep it recognizable at small sizes.

---

## Step 2: Web App Manifest

Create `public/manifest.json`:

```json
{
  "name": "Coach Exercise Tracker",
  "short_name": "Coach",
  "description": "Personal workout tracker and exercise coach",
  "start_url": "/exercise",
  "display": "standalone",
  "background_color": "#1a1a2e",
  "theme_color": "#1a1a2e",
  "orientation": "portrait",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable" },
    { "src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

---

## Step 3: Update `public/index.html` Head

Add to `<head>`:

```html
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icons/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<meta name="description" content="Personal workout tracker and exercise coach">
```

Add before closing `</body>`:

```html
<script>
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js');
  }
</script>
```

---

## Step 4: Service Worker (`public/sw.js`)

Strategy: **Network-first with offline fallback** for HTML/CSS/JS, respecting the existing cache-busting mechanism.

### What to cache

- App shell: `/exercise`, `/styles.css`, `/js/app.js`, `/js/store.js`, `/js/utils.js`, all component JS files:
  - `/js/components/Header.js`
  - `/js/components/DateSelector.js`
  - `/js/components/CalendarPicker.js`
  - `/js/components/BlockView.js`
  - `/js/components/WorkoutView.js`
  - `/js/components/ExerciseItem.js`
  - `/js/components/SetEntry.js`
  - `/js/components/CardioEntry.js`
  - `/js/components/ChecklistEntry.js`
  - `/js/components/SessionFeedback.js`
  - `/js/components/Notifications.js`
- Icons and manifest
- CDN imports from esm.sh (Preact, htm, localforage, signals)

### What NOT to cache

- API calls (`/api/*`) — data sync is handled by LocalForage already

### Cache lifecycle

- On `install`: pre-cache app shell and CDN dependencies
- On `fetch` (app shell): try network first, fall back to cache. Update cache on successful network response.
- On `fetch` (CDN): cache-first (these are versioned/immutable URLs)
- On `fetch` (API): network-only, let LocalForage handle offline data
- On `activate`: clean up old caches

### Cache versioning

Use a `CACHE_VERSION` constant in the service worker. Bump it on deploys. On `activate`, delete caches with old version names.

### Consideration: server cache-busting

The server appends `?v={uuid}` to CSS/JS URLs on each restart. The service worker should cache by stripping query params (or cache the versioned URL and pre-cache on install). Simplest approach: cache the response regardless of query params, keyed by the base path.

---

## Step 5: Serve Manifest and Icons from FastAPI

Update `src/server.py`:

- Add route to serve `manifest.json` (with `application/manifest+json` content type, no-cache)
- Add route to serve files from `public/icons/` (with long cache headers — icons are static)
- Add route to serve `sw.js` from `public/` root (with `no-cache` and `Service-Worker-Allowed: /` header)

---

## Step 6: Install Prompt (Optional Enhancement)

Capture the `beforeinstallprompt` event in `app.js` to show a custom install button/banner. This is low priority — browsers show their own install UI automatically when the manifest criteria are met.

---

## Implementation Order

1. **Icons** — create the SVG and generate PNGs
2. **manifest.json** — create the file
3. **HTML head updates** — add manifest link, icon links, SW registration
4. **Server routes** — serve manifest, icons, and service worker
5. **Service worker** — implement caching logic
6. **Test** — verify installability in Chrome DevTools > Application > Manifest

---

## Installability Checklist (Chrome)

All of these must pass for the browser to show an install prompt:

- [ ] Served over HTTPS (or localhost)
- [x] Has a web app manifest with `name`, `icons` (192+512), `start_url`, `display`
- [x] Has a registered service worker with a `fetch` event handler
- [x] Icons are fetchable and correct sizes
