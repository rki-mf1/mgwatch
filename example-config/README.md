# Example image deployment config

This directory is a template for image-based deployments. Copy `.env.example` to
`.env` and `vars.env.example` to `vars.env` in the deployment directory, then
replace every `CHANGE_ME` value before starting services.

Start the stack with:

```bash
docker compose -f compose.prod.yml up -d
```

Only `mgwatch-proxy` publishes a host port. MongoDB and Redis are internal
Compose services and should not be exposed in production.
