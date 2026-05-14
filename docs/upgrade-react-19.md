# React 19 migration plan

_Last updated: ${current_date}_

The frontend currently targets **React 18.3.1**. React 19 is GA on npm
and brings a handful of changes that, while mostly additive, do
include enough breaking-API tweaks to merit an explicit migration
plan before we lift the pin in `frontend/package.json`.

This document does **not** contain a code patch — that work needs a
green CI run in a separate PR. The goal here is to enumerate
everything we will have to touch, give every item an owner-of-this-PR
checkable acceptance criterion, and rough out an execution order.

---

## Current pinned versions

```
"react":          "^18.3.1"
"react-dom":      "^18.3.1"
"@types/react":   "^18.3.10"
"framer-motion":  "^11.5.4"
"typescript":     "^5.5.4"
```

React 19 requires `@types/react ≥ 19`, `typescript ≥ 5.0`, and a
`react-dom` version matching the major. Framer Motion ≥ 11.11
declares React 19 in `peerDependencies`; older 11.x versions warn
but still work with the React 19 runtime in practice.

---

## Breaking changes that apply to this codebase

### 1. `forwardRef` is no longer needed for `ref` forwarding

React 19 lets function components accept `ref` as a regular prop,
and the team recommends migrating off `forwardRef` because it will
be deprecated in a future major. We have four call sites:

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
   was written needs a fix before the bump.
2. **Bump types and TS first** — `@types/react@^19`, `@types/react-dom@^19`
   on the existing React 18 runtime. The compiler errors guide the
   `forwardRef` and other API migrations.
3. **Migrate `forwardRef`** — the four `frontend/src/components/ui/*.tsx`
   files. Run `npx tsc -b` to confirm types still pass.
4. **Bump React + ReactDOM** — `react@^19` and `react-dom@^19`.
   Run the full test suite (`npx vitest run` once we have it,
   manual smoke testing of the TMA otherwise) and Cypress / E2E
   coverage if available.
5. **Bump Framer Motion** to `^11.11` (the first version that
   advertises React 19 as a peer dep). Verify animations on the
   deal-flow page and the home screen.
6. **Smoke-test in production-like build** — `npm run build` and a
   manual click-through of the staging environment.

---

## Out of scope for this doc

- Server Components / React Server Functions — we don't have a
  Next.js or Remix layer; the TMA is a pure SPA.
- Compiler (the React Forget / React Compiler) — opt-in, separate
  consideration.
- Concurrent feature adoption beyond what we already use.
