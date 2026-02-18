# triagedeck

## Quick Start (local)

- `just bootstrap`
- `just dev`

API: `http://127.0.0.1:8000`
Client: `http://127.0.0.1:8080`

Auth for local testing: set request header `x-user-id` to one of:

- `admin@example.com`
- `reviewer@example.com`
- `viewer@example.com`

Client keyboard shortcuts:

- `Left`/`Right`: previous/next item
- `P`: PASS decision
- `F`: FAIL decision
- `R`: force sync

## Developer Commands (`just`)

- `just bootstrap`
- `just dev`
- `just test`
- `just test-api` (core API tests + live HTTP contract tests with explicit skip reasons)
- `just lint`
- `just fmt`
- `just check`
- `just db-upgrade`
- `just db-reset`
- `just seed`
- `just export-smoke`
