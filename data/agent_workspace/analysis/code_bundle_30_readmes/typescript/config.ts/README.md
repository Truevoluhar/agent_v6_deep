# config.ts

- **Source file:** `/uploads/code_bundle_30/typescript/config.ts`
- **Language:** TypeScript
- **Purpose:** Defines a configuration shape and exports a default configuration value.
- **Key functions/classes:** Type alias `Config`; exported constant `defaultConfig`.
- **Inputs:** No runtime input; consumers import `defaultConfig` or reuse the `Config` type internally if exported later.
- **Outputs:** Exports `{ retries: 3, verbose: false }` as `defaultConfig`.
- **Notable implementation details:** `Config` is not exported, so only this module can reference the named type directly; TypeScript erases the type at runtime.
