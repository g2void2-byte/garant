// Flat-config equivalent of the legacy .eslintrc.cjs we used before
// migrating to ESLint 9. Behaviour is intentionally preserved 1:1 —
// the only purpose of this change is to unblock the dependabot bump
// for ``eslint-plugin-react-refresh@0.5.x``, which dropped support
// for the legacy ``eslintrc`` format and now declares ESLint 9 as a
// peer.
//
// Notes for future readers:
//
// * The ``files: ['src/**/*.{ts,tsx}']`` scope mirrors the historical
//   ``npm run lint`` invocation (``eslint --ext .ts,.tsx src``). The
//   package.json script now just passes ``src`` as a positional and
//   ESLint resolves the relevant files from the config.
// * ``ignores`` mirrors the legacy ``ignorePatterns`` minus entries
//   that ESLint 9 already excludes by default (``node_modules`` is
//   never traversed; ``dist`` is the build output). ``.eslintrc.cjs``
//   has been removed entirely, so no ignore entry for it is needed.
// * We bypass the ``typescript-eslint`` meta-package and wire the
//   parser/plugin directly so we keep the same pinned versions of
//   ``@typescript-eslint/{parser,eslint-plugin}`` already declared in
//   package.json.

import js from '@eslint/js';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';

export default [
  {
    ignores: ['dist/**', '**/*.config.js', '**/*.config.ts'],
  },
  js.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      // ``no-undef`` is unaware of TS types (it complains about
      // ``React`` used purely as a JSX-namespace type, about DOM
      // lib types like ``EventListenerOptions`` etc.) — TypeScript
      // itself handles unresolved identifiers, so the rule is
      // pure noise on a TS codebase. The legacy eslintrc setup
      // got this turned off implicitly via ``parser:`` resolution;
      // flat config requires it to be explicit.
      'no-undef': 'off',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-empty-object-type': 'off',
      // M-5 — keep the CSP contract enforceable from the lint stage.
      //
      // The backend serves ``style-src 'self'`` / ``style-src-elem
      // 'self'`` / ``style-src-attr 'none'`` / ``script-src 'self'
      // https://telegram.org`` / ``script-src-attr 'none'`` on every
      // response (see ``backend/app/main.py::_CSP_DIRECTIVES`` and
      // ``docs/csp-policy.md``). A JSX element that emits an inline
      // ``<style>`` block, a ``<script>`` tag, a third-party
      // ``<link rel="stylesheet" href="https://...">``, or that uses
      // ``dangerouslySetInnerHTML`` reopens exactly the inline-style
      // / inline-script injection vector M-5 was filed to close.
      //
      // ``react/no-danger`` would do the ``dangerouslySetInnerHTML``
      // check for us but we deliberately avoid pulling in the full
      // ``eslint-plugin-react`` (the project only depends on
      // ``-hooks`` / ``-refresh``). ``no-restricted-syntax`` with
      // ESLint's built-in JSX AST selectors covers all four cases
      // without a new plugin.
      //
      // If a future change genuinely needs one of these — e.g.
      // server-side rendering pre-loading a critical CSS chunk via
      // ``<style>`` — the diff has to add a per-file ``eslint-disable``
      // (NOT a config relax) plus a sibling change to
      // ``_CSP_DIRECTIVES`` and ``tests/test_csp_policy.py``. The
      // three-way coupling makes the policy decision explicit in
      // code review.
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXOpeningElement[name.name='style']",
          message:
            "CSP forbids inline <style> tags (style-src-elem 'self'). " +
            'Import a .css module from src/styles.css or src/**/*.module.css. ' +
            'See docs/csp-policy.md.',
        },
        {
          selector: "JSXOpeningElement[name.name='script']",
          message:
            "CSP forbids inline <script> tags (script-src 'self' " +
            'https://telegram.org). Add a same-origin module under src/ ' +
            'and import it from main.tsx. See docs/csp-policy.md.',
        },
        {
          selector:
            "JSXOpeningElement[name.name='link']:has(JSXAttribute[name.name='rel'][value.value='stylesheet'])",
          message:
            "CSP forbids cross-origin stylesheets (style-src-elem 'self'). " +
            'Vendor the stylesheet under src/ or extend script-src in ' +
            'backend/app/main.py AND tests/test_csp_policy.py. See ' +
            'docs/csp-policy.md.',
        },
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message:
            'dangerouslySetInnerHTML can inject inline <style> / <script> ' +
            'markup that CSP would silently block on first paint. Render ' +
            'the value as a React child instead. See docs/csp-policy.md.',
        },
      ],
    },
  },
];
