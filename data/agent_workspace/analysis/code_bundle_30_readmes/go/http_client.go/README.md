# http_client.go

- **Source file:** `/uploads/code_bundle_30/go/http_client.go`
- **Language:** Go
- **Purpose:** Provides a helper that performs an HTTP GET and returns the response status code as a string.
- **Key functions/classes:** `status(url string) string` fetches the URL and formats `res.StatusCode`.
- **Inputs:** A URL string passed to `status`.
- **Outputs:** Returns the numeric HTTP status code formatted as text, such as `200`.
- **Notable implementation details:** Uses `net/http.Get` and `fmt.Sprintf`; the error returned by `http.Get` is ignored, so failed requests can cause a nil-pointer panic when accessing `res.StatusCode`.
