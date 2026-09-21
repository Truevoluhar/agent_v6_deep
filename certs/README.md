Place private vLLM TLS or mTLS certificate files in this directory.

This folder is mounted into `agent-api` as `/certs`, so files placed here on the host are available inside the container at the same names under `/certs`.

Recommended filenames:

- `internal-ca.pem` — PEM-encoded private CA bundle used to verify the vLLM server
- `client.pem` — PEM-encoded client certificate for mTLS
- `client.key` — private key for `client.pem`

Example `.env` configuration:

```dotenv
ACTIVE_PROVIDER=vllm
VLLM_BASE_URL=https://your-vllm-host:8000/v1
VLLM_API_KEY=dummy

VLLM_TLS_VERIFY=/certs/internal-ca.pem
VLLM_CA_FILE=/certs/internal-ca.pem
VLLM_CLIENT_CERT_FILE=/certs/client.pem
VLLM_CLIENT_KEY_FILE=/certs/client.key
```

Notes:

- OpenAI does not use files from this directory in this project.
- `.crt` files are also fine if they are PEM-encoded.
- If your CA chain has multiple certificates, combine them into one PEM bundle.
