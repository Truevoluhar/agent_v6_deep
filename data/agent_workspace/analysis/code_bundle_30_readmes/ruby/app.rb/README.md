# app.rb

- **Source file:** `/uploads/code_bundle_30/ruby/app.rb`
- **Language:** Ruby
- **Purpose:** Defines a text title-casing helper and demonstrates it.
- **Key functions/classes:** `titleize(text)` splits text into words, capitalizes each word, and rejoins them.
- **Inputs:** A string passed to `titleize`; the script uses `ruby sample app`.
- **Outputs:** Returns the titleized string; prints `Ruby Sample App` in the sample invocation.
- **Notable implementation details:** Uses `split`, symbol-to-proc shorthand `map(&:capitalize)`, and `join(' ')`; whitespace is normalized to single spaces.
