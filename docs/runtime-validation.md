# Runtime API-response validation — current state & trade-offs

> Audit ref: **A-8** (audit v11). Status: *partially closed* by V12-H5
> (#103); the long-form section here exists so the next reader of the
> codebase doesn't have to recover the trade-off from PR archaeology.

## TL;DR

Compile-time we are strict; **runtime we are not**.

| Layer | What protects us | What can still slip through |
|---|---|---|
| `tsc --noEmit` against `openapi.generated.ts` | Field renames, nullability flips, removed routes — any drift between `frontend/openapi.json` (regenerated from `backend/app/main.py`) and the DTOs the UI reads. | A schema change that's *not* reflected in `openapi.json` because the backend was edited without re-running the typegen pipeline. |
| `openapi.contract.test.ts` (vitest) | Representative fixtures (`UserOut`, `DealOut`, `WalletBalanceOut`, `CurrencyOut`, `PinStatusOut`) keep satisfying `components["schemas"]`; missing top-level schemas (e.g. `NotificationOut`) fail the suite. | Same blind spot as `tsc` — driven by the committed `openapi.json`. |
| `npm run check:api-drift` (CI gate, V12-H5 / #103) | The backend is started in CI, the OpenAPI schema is re-dumped, and any byte-level diff vs. the committed `openapi.json` fails the build. | Field-level drift inside a free-form payload that the schema models as `additionalProperties: true` (we have none currently, but it's the theoretical hole). |
| `app/api/client.ts` (`ky` instance) | TLS / HTTP errors, the PIN-session 401 contract, the 5xx retry budget. | The shape of a `200 OK` body — `ky` returns whatever JSON the server sent. |

Concretely: **no runtime validator is invoked between `await response.json()` and React state**. If a buggy/forked backend ever returned a `DealOut` with `amount: "100"` (string) instead of `100` (number), the UI would render `NaN` for the commission because the formatter calls `Number(deal.amount) - …`. Today we rely on the contract test + drift gate to catch that *in CI*, before such a backend can be deployed.

## Why we don't currently codegen runtime validators

We considered three approaches; all of them have non-trivial costs that, given the V12-H5 drift gate, weren't worth taking on yet.

### 1. `openapi-zod-client` / `zodios` (Pydantic → Zod)

Pros: Clean DX; the validators come for free off the same `openapi.json` we already generate; we'd get human-readable error messages.

Cons:

- Adds a runtime dependency (`zod`, ~10 KB gzipped on the hot path).
- Generates ~7–10 KB of validator code on top of the existing
  `openapi.generated.ts`. We currently sit at ~37 schemas in
  `openapi.json`; the wallet/withdrawal/notification branches add
  another ~15 each. Bundling cost matters more than CPU here.
- The generators we evaluated emit classes; we'd need to either fork
  to emit functions or to ship a thin wrapper that calls
  `.parse()`. Not a blocker, but it's *some* code we'd own.
- Pydantic's `discriminator: type` unions don't survive the round-trip
  through `openapi-typescript` 7.x perfectly — the generated schema
  is correct but a number of TS-side generators emit an over-wide
  union that ends up *less* precise than what `tsc` already gives
  us via `components["schemas"]`.

### 2. Bespoke hand-written guards (`isDealOut`, `isUserOut`, …)

Pros: Zero new dependencies, zero codegen step, smallest bundle delta.

Cons: They duplicate the schema by hand, which is exactly the drift
risk the audit raised. Maintenance burden falls back on whoever last
touched the schema — easy to forget.

### 3. Schema-driven validators emitted at build time (`json-schema-to-zod`, `quicktype`)

Pros: One codegen step, no manual maintenance, smaller emit than
`openapi-zod-client` because we control which schemas we emit
validators for.

Cons: Same bundle-size and union-precision concerns as (1), and we'd
own the build step.

### Why V12-H5 was enough for now

The audit notes that V12-H5 (#103) "**partially closes**" A-8. That's
accurate: a drifted backend is now caught *deterministically* by
`scripts/dump_openapi.py` + `npm run check:api-drift` running in the
backend CI job before either side ships. The remaining hole — a
backend that lies *consistently* (i.e. its `openapi.json` says one
thing, its runtime responses say another) — is realistically a
post-mortem-grade bug, and a runtime validator on the frontend would
only convert "blank UI" into "blank UI with a console error". Useful,
but not free.

## When to revisit

Re-open A-8 (full runtime validator codegen) when **any** of these
become true:

1. We start consuming partner / third-party APIs whose schema we
   don't control (today every backend route is in this repo).
2. We add a `additionalProperties: true` schema (i.e. a payload
   shaped like a discriminated union where the discriminant is data,
   not type) — those slip past `tsc` even when `openapi.json` is
   accurate.
3. The wallet team needs to deserialise `Decimal`-style strings (the
   current Numeric columns serialise as JSON numbers and we have a
   `.spec` regression that catches the boundary; once we move to
   `decimal.js`, runtime parsing of a *string* payload becomes
   load-bearing and a guard pays for itself).
4. The contract-test surface grows past ~30 fixtures — at that point
   the hand-maintained `as const satisfies` block in
   `openapi.contract.test.ts` becomes harder to skim than a generated
   validator.

## Migration recipe (when we do open it)

1. Pin `openapi-zod-client` (or the chosen generator) at a known
   version; add it as a `devDependency` and a `prebuild` step that
   reads `openapi.json` and emits `frontend/src/api/openapi.zod.ts`.
2. Mark the emitted file `// AUTO-GENERATED. DO NOT EDIT.` (we already
   have that header on `openapi.generated.ts`; the new file mirrors it).
3. Add a thin wrapper around the existing `ky` instance:

   ```ts
   // pseudocode — not committed
   export async function getJson<TName extends keyof Schemas>(
     name: TName,
     path: string,
     init?: KyOptions,
   ): Promise<Schemas[TName]> {
     const raw = await api.get(path, init).json();
     return schemas[name].parse(raw);  // emits a typed Zod error
   }
   ```

4. Replace one route at a time — start with `GET /api/wallet/balance`
   (highest read volume) and grow outwards. **Do not** flag-day the
   whole codebase; the value of incremental rollout is that it shakes
   out backend lies as we discover them, instead of one big-bang day
   of debugging.
5. Wire the runtime errors to Sentry (already a dep in `frontend/`)
   so a single bad deploy surfaces immediately.

Until then: keep the drift gate green, keep `openapi.contract.test.ts`
under control, and **do not** allow a "schema drift OK, just override
locally" workaround to land — that's the only way the safety net
actually fails.
