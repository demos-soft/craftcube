// ESLint flat config — first-party frontend only.
// Vendored third-party code (TinyMCE, bootstrap) and generated CSS are
// excluded: we lint what we own, like the backend rule set does.
import globals from "globals";

export default [
  {
    ignores: [
      "app/static/tinymce/**",
      "app/static/deps/**",
      "app/static/styles/*.min.css",
      "node_modules/**",
    ],
  },
  {
    files: ["app/static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "script",
      globals: {
        ...globals.browser,
        // vendored/runtime-provided globals the first-party scripts use
        tinymce: "readonly",
        TinyMCE: "readonly",
        jQuery: "readonly",
        $: "readonly",
        bootstrap: "readonly",
        // templates define these inline before our scripts run
        CC_ENV: "readonly",
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      // eslint:recommended is the baseline; on top of it:
      "no-unused-vars": ["error", {
        args: "none",
        // catch bindings exist purely as cross-origin guards, ported from
        // the reference verbatim (Roundcube ui.js/editor.js idiom)
        caughtErrors: "none",
        // the ports keep reference helpers alive even where CraftCube
        // currently has no caller (find_object, panes, abs_url)
        varsIgnorePattern: "^(find_object|panes|abs_url)$"
      }],
      // ports of ui.js/editor.js compare env strings against each other;
      // every remaining site is string/string or number/number, so the
      // loose form is dead weight: strict equality everywhere
      eqeqeq: ["error", "always"],
      "no-var": "off", // ES5-style ports of Roundcube's ui.js stay var-clean
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "prefer-const": ["error", { destructuring: "all" }],
      "one-var": ["error", "never"], // declaration hygiene without banning var
      "no-else-return": "error",
      "no-lonely-if": "error",
      "no-throw-literal": "error",
      // shadowing BUILTINS stays allowed: the module wrappers take
      // (window, document) as UMD parameters and the ports keep locals
      // like `parent`/`open`/`focus` from the reference source.
      // Shadowing outer user variables is what actually invites bugs.
      "no-shadow": ["error", { builtinGlobals: false }],
      curly: ["error", "multi-line"],
      "no-fallthrough": "error",
    },
  },
];
