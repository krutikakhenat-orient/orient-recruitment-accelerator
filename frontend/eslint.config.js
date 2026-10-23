import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    plugins: {
      // Register the React Hooks plugin so its rules are defined. Without this, any
      // `// eslint-disable ... react-hooks/*` comment errors with "rule not found".
      "react-hooks": reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser },
    },
    rules: {
      // Rules of Hooks violations are real bugs — keep them as errors (never suppressed).
      "react-hooks/rules-of-hooks": "error",
      // Start exhaustive-deps as a warning so it surfaces missing/extra deps without
      // failing CI; the lint script has no --max-warnings, so warnings don't break the build.
      "react-hooks/exhaustive-deps": "warn",
    },
  },
);
