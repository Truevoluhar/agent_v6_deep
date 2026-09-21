# Dockerfile

- **Source file:** `/uploads/code_bundle_30/docker/Dockerfile`
- **Language:** Dockerfile
- **Purpose:** Defines a lightweight Python container image for running an `app.py` application.
- **Key functions/classes:** Docker instructions: `FROM`, `WORKDIR`, `COPY`, and `CMD`.
- **Inputs:** Build context contents are copied into `/app`; expects `app.py` to exist in the image.
- **Outputs:** Produces a container image that runs `python app.py` by default.
- **Notable implementation details:** Uses the `python:3.12-slim` base image and copies the entire build context into the working directory.
