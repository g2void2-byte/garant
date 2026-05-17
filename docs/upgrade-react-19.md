# React 19 migration plan

_Last reviewed: 2026-05-17 (V12-M12)._
_Last code-touch: still on React 18.3.1 — no migration PR opened yet._

The frontend currently targets **React 18.3.1**. React 19 has been GA
on npm since 2024-12 (`react@19.0.0`) and brings a handful of
changes that, while mostly additive, do include enough breaking-API
tweaks to merit an explicit migration plan before we lift the pin in
`frontend/package.json`.

This document does **not** contain a code patch — that work needs a
green CI run in a separate PR. The goal here is to enumerate
everything we will have to touch, give every item an owner-of-this-PR
checkable acceptance criterion, and rough out an execution order.

---

## Current pinned versions

From `frontend/package.json` (pinned without `^` per V12-M3):

```
"react":          "18.3.1"
"react-dom":      "18.3.1"
"@types/react":   "18.3.28"
"@types/react-dom": "18.3.7"
"@tanstack/react-query": "5.100.10"
"framer-motion":  (not in deps — removed since this doc was first written)
"typescript":     "~5.7"
```

React 19 requires `@types/react ≥ 19`, `typescript ≥ 5.0`, and a
`react-dom` version matching the major. **TanStack Query**: 5.55+ is
the minimum that supports React 19's hooks API; we are already on
5.100.x, so this is no longer a blocker (it _was_ at the time this
doc was first drafted on TanStack 5.51). Framer Motion ≥ 11.11
declares React 19 in `peerDependencies`; older 11.x versions warn
but still work with the React 19 runtime in practice — moot for us
right now since Framer Motion was removed from the dependency list.

---

## Breaking changes that apply to this codebase

### 1. `forwardRef` is no longer needed for `ref` forwarding

React 19 lets function components accept `ref` as a regular prop.
`forwardRef` is **deprecated** in 19 (still works, prints a warning
in dev) and the React team has flagged it for removal in a **future
major** (currently slated for React 20, no firm date). Migrating off
it now means the runtime warning stops showing up and the codebase
doesn't accumulate technical debt to clean up at the next bump.

We have four call sites:

- `frontend/src/components/ui/Button.tsx`
- `frontend/src/components/ui/Input.tsx`
- `frontend/src/components/ui/Textarea.tsx`
- `frontend/src/components/ui/Card.tsx`

Each is the `forwardRef<HTMLElement, Props>(function …)` pattern.
Migration is mechanical:

```tsx
// Before
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, ...rest }, ref) {
    return <button ref={ref} {...rest} />;
  },
);

// After
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  ref?: React.Ref<HTMLButtonElement>;
};
export function Button({ className, ref, ...rest }: ButtonProps) {
  return <button ref={ref} {...rest} />;
}
```

**Acceptance**: after the migration, `git grep forwardRef frontend/src`
returns nothing.

### 2. `defaultProps` on function components is gone

React 19 removes `defaultProps` for function components entirely;
class components keep it. We don't currently use `defaultProps`
anywhere in `frontend/src/` (verified by
`git grep defaultProps frontend/src/`), so this is a no-op for us
today, but the migration plan should re-check this immediately
before bumping the dep because new code lands frequently.

**Acceptance**: `git grep -nE 'Component\.defaultProps' frontend/src/`
returns nothing on the migration branch.

### 3. `propTypes` runtime check is gone

Same story — we use TypeScript end-to-end, so no `propTypes` survive
in `frontend/src/`. Re-verify on the migration branch.

**Acceptance**: `git grep -nE 'propTypes' frontend/src/` returns
nothing on the migration branch.

### 4. `<form action>` now supports server actions / async functions

React 19 reinterprets `<form action={fn}>` to mean "run this async
function on submit and feed the result back through `useActionState`".
That's a feature, not a breaking change *if* you only ever passed
strings to `action=` — and we currently don't have any `<form
action=…>` JSX (verified with `git grep -n '<form action' frontend/src/`).
We can opt into this idiom for the deal-create / arbitration-open /
review-submit flows after the bump.

### 5. `useReducer` initialiser changes

Initialiser is now typed as `(arg: T) => S` instead of
`(arg?: T) => S`. Practical impact: TypeScript will start refusing
to call your initialiser with no argument. We don't use `useReducer`
extensively today (`git grep useReducer frontend/src/` is empty
right now); if any new code adds it before the bump, audit the
initialiser signatures.

### 6. JSX namespace moved from global to `React`

`JSX.Element` etc. live under `React.JSX` now. The TypeScript-side
of the bump (jumping to `@types/react@19`) will surface any
`JSX.Element` references that aren't already imported from React.
We currently have **zero** bare `JSX.` references in `frontend/src/`
(verified with `git grep -nE '\bJSX\.' frontend/src/`), so this is
a no-op today.

### 7. `ReactDOM.render` / `ReactDOM.hydrate` removal

These were soft-deprecated in React 18 and removed in React 19.
The codebase already uses `createRoot` / `hydrateRoot` from
`react-dom/client` (see `frontend/src/main.tsx`), so this is a
no-op for us.

---

## Adoption opportunities (post-migration)

These are *not* required for the version bump, but they're worth
doing in a follow-up once we're on React 19 — they unlock
measurable wins.

### `use()` for promise unwrapping

The `use()` hook can replace `useEffect`+`useState` for the handful
of one-shot async lookups we do (e.g. fetching the user profile,
deal detail page). Smaller bundle, no flicker.

### `useActionState` for form submissions

Most of our form handlers (PIN setup, deal create, transfer
confirm) are doing the `setBusy(true) / await … / setBusy(false)`
dance manually. `useActionState` collapses that into the standard
React 19 idiom and frees us from re-implementing the same loading +
error state on every form.

### Improved `Suspense` semantics

React 19 reorders `Suspense` so siblings of a suspended subtree no
longer get re-mounted on resume. We have one place (`DealsList`)
where this currently causes a visible re-fetch on scroll-back; the
upgrade should make that disappear without a code change.

---

## Suggested execution order

1. **Audit** — re-run the `git grep` checks listed under each section
   on the migration branch. Anything new that landed since this doc
   was last reviewed needs a fix before the bump. Pay attention to
   `forwardRef` (new call sites tend to accumulate quickly), `JSX.`
   bare references, and any new `useReducer` initialisers.
2. **Bump types and TS first** — `@types/react@19`, `@types/react-dom@19`
   (pinned without `^` per V12-M3) on the existing React 18 runtime.
   The compiler errors guide the `forwardRef` and other API
   migrations. CI's `npm run typecheck` gate (V12-M4) is the
   primary green-bar here.
3. **Migrate `forwardRef`** — the four `frontend/src/components/ui/*.tsx`
   files. `npm run typecheck` must stay green; `git grep forwardRef
   frontend/src` returns nothing.
4. **Bump React + ReactDOM** — `react@19` and `react-dom@19` (pinned
   without `^`). Run the full test suite (`npm run test:run`
   covers vitest, `npm run test:e2e` covers Playwright) and verify
   `npm run build` succeeds. Dependabot (V12-M3) will continue to
   open weekly bump PRs on top of the new major.
5. **Skip Framer Motion** — no longer a dependency in this codebase
   (was removed since this doc was first written). If it gets
   re-added, pin to ≥ 11.11 so the React 19 peer-dep is satisfied.
6. **Re-generate the OpenAPI typings** — `npm run generate:api-types`
   then confirm `git diff --exit-code` on `src/api/openapi.generated.ts`
   is empty. The drift gate (V12-H5/L7) will fail CI otherwise.
7. **Smoke-test in production-like build** — `npm run build` and a
   manual click-through of the staging environment.

---

## Out of scope for this doc

- Server Components / React Server Functions — we don't have a
  Next.js or Remix layer; the TMA is a pure SPA.
- Compiler (the React Forget / React Compiler) — opt-in, separate
  consideration.
- Concurrent feature adoption beyond what we already use.

---

## Review log

- **2026-05-17 (V12-M12 — refresh)** — Confirmed the audit's blocking
  notes are no longer accurate: TanStack Query is on 5.100.x (the
  5.51 → 5.55+ hop happened in #105/V12-M3), Framer Motion is no
  longer a dependency. Tightened the `forwardRef` deprecation
  statement (deprecated-not-removed in 19, removal slated for 20),
  pulled the inline `${current_date}` placeholder, swapped the
  caret-version examples to the exact pins now in `package.json`,
  added the OpenAPI re-gen step to the execution order so the
  drift gate (V12-H5/L7) doesn't ambush the migration PR.
