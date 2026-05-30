# Content Security Policy

The backend sets one global CSP header in `backend/app/main.py`. The default policy is intentionally strict:

- no inline scripts or inline styles;
- scripts may load only from the app origin and `https://telegram.org`;
- images may load from same-origin, `data:`, `blob:`, and HTTPS URLs;
- `connect-src` defaults to `'self'` and can be widened with `CSP_CONNECT_SRC` or `PUBLIC_API_URL` for split frontend/API deployments;
- `frame-ancestors` allows the app origin plus Telegram Web origins only;
- violations are reported to `/api/csp-report`.

Do not add `'unsafe-inline'` or `'unsafe-eval'`. If a dependency requires inline style/script injection, replace the dependency or isolate that feature behind an explicit CSP review. The frontend ESLint config blocks JSX `<style>`, `<script>`, and stylesheet `<link>` elements for the same reason.

When adding a new CDN or API origin:

1. Prefer a config variable over hard-coding the origin.
2. Update the CSP snapshot tests in `tests/integration/test_csp_policy.py` if the default policy changes.
3. Document why the new origin is needed and whether it is used in production, staging, or local development only.

For split deployments where the frontend is served from the backend but API/WebSocket calls go to another origin, set either:

```env
PUBLIC_API_URL=https://api.example.com
```

or the full directive:

```env
CSP_CONNECT_SRC='self' https://api.example.com wss://api.example.com
```
