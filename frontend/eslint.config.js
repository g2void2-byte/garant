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
    },
  },
];
