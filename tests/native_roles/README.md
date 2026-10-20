# Native CE roles fixture

This opt-in fixture uses the exact saved 0.1.1 package, pinned ARM64 Dify API/worker
and daemon images, PostgreSQL 16.10, Redis 8 and a synthetic HTTPS endpoint. It
needs Docker Compose and Python 3.12 with Requests and cryptography available.
It is excluded from default pytest collection and the runtime packaging allowlist.

Run from the repository root, replacing the archive path with your saved artifact:

```sh
python tests/native_roles/run.py --self-check
python tests/native_roles/run.py --archive /absolute/path/mailchannels-0.1.1.difypkg --fail-before-credentials
python tests/native_roles/run.py --archive /absolute/path/mailchannels-0.1.1.difypkg
```

The archive must match SHA-256
`276ba4fe72c81df1f3d68c79b6b79ffec7f4430c5df93cc2a255053373ab9f8d`.
The fixture never rebuilds it. Pull the images named in `run.py` first; all other
native services run on one internal Docker network without published ports.
Docker Desktop does not publish ports from that network. The small stdio broker
makes real authenticated HTTP requests to localhost inside the API container,
including the native cookie and CSRF checks. Seed services create only synthetic
accounts and memberships in the owned database, without invitation email.

A separate temporary container fetches Linux ARM64 wheels from the public Python
package registry, then exits before credentials exist. The daemon installs these
wheels itself using `--no-index`. Generated CA trust maps the fixed
`api.mailchannels.net` endpoint to the owned mock, with certificate verification
on. Before credentials, the fixture checks the internal network, native daemon
DNS/TLS and blocked external egress. After installation it checks default Requests
TLS/proxy behavior in the actual plugin interpreter. It sends no real mail and
uses no model provider, SMTP service, company account or Marketplace endpoint.

Each run writes a private `$TMPDIR/dify-native-roles-01a122b4-*` evidence
directory. `acceptance.json` contains sanitized results, artifact/image identities,
wheel hashes and cleanup status; `log-hashes.json` identifies sanitized logs.
Mock records contain only fixture labels, request status/mode and payload/routing
hashes. API keys, passwords, cookies and full email addresses are excluded from
shared evidence. Generated secrets and wheels are removed after successful
container teardown. Database and runtime volumes are removed only for the exact
owned Compose project; existing running containers must remain unchanged.

A failed setup or assertion produces a failed result and still attempts cleanup.
`--fail-before-credentials` must produce `controlled_failure_cleaned` with zero
provider requests. Do not infer acceptance from a partial run, or share secret
files if cleanup fails. Cleanup deletes native credentials, proves old workflows
cannot invoke the mock, uninstalls the plugin, checks zero scoped database rows,
removes fixture apps and tears down only owned containers and volumes.

The matrix characterizes the five legacy Community Edition roles with
`RBAC_ENABLED=false`. Private credential visibility filters ordinary listings;
it does not forbid same-workspace workflow use by credential ID or default
selection. See `docs/NATIVE_VALIDATION.md` for observed results and open scope.
