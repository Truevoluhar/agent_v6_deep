# user.ts

- **Source file:** `/uploads/code_bundle_30/typescript/user.ts`
- **Language:** TypeScript
- **Purpose:** Defines a user data shape and a formatter for user values.
- **Key functions/classes:** Exported interface `User`; exported function constant `formatUser`.
- **Inputs:** `formatUser` accepts a `User` object with string `id` and `name` fields.
- **Outputs:** Returns a string formatted as `<id>:<name>`.
- **Notable implementation details:** Uses an arrow function and template literal; the `User` interface is compile-time only and produces no runtime validation.
