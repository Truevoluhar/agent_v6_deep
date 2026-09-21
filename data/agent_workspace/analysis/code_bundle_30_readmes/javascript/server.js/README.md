# server.js

- **Source file:** `/uploads/code_bundle_30/javascript/server.js`
- **Language:** JavaScript / Node.js
- **Purpose:** Starts a very small HTTP server.
- **Key functions/classes:** Uses `http.createServer((req, res) => { ... })` with a request handler callback.
- **Inputs:** HTTP requests sent to port `3000`; request details are not inspected.
- **Outputs:** Responds to every request with the body `ok`.
- **Notable implementation details:** Uses Node's built-in `http` module and listens on port `3000`; it does not set explicit status codes or headers.
