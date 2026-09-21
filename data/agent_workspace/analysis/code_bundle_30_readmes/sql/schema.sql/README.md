# schema.sql

- **Source file:** `/uploads/code_bundle_30/sql/schema.sql`
- **Language:** SQL
- **Purpose:** Defines a `users` database table schema.
- **Key functions/classes:** `create table users` statement with columns `id`, `email`, and `created_at`.
- **Inputs:** Executed by a SQL database engine or migration tool.
- **Outputs:** Creates a table where `id` is the primary key, `email` is required and unique, and `created_at` is required text.
- **Notable implementation details:** Uses generic SQL column types (`integer`, `text`); timestamp values are represented as text rather than a database-native datetime type.
