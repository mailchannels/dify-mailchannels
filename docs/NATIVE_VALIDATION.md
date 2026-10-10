# Native validation scope

This is a development candidate, not a Marketplace release. All provider traffic
in these checks went to a local synthetic HTTPS mock. No live MailChannels
validation, delivered email, Cloud deployment or Marketplace acceptance is claimed.

## Tested artifact

- Plugin version: 0.1.1.
- Runtime source commit: `1bd81ec9b7a0334635e91bd0e179b20a96a082bf`.
- Archive SHA-256: `276ba4fe72c81df1f3d68c79b6b79ffec7f4430c5df93cc2a255053373ab9f8d`.
- Native platform: Dify Community Edition 1.17.1, daemon 0.6.10-local.
- Validation date: October 7, 2026.

Later documentation edits do not retroactively validate a rebuilt archive.
Before submission, rebuild the reviewed source, record the new archive hash, run
its SDK/packaged-runtime checks, and repeat native acceptance on that exact archive.

## Observed results

| Surface | Evidence and boundary |
| --- | --- |
| Installation | Exact archive installed through the native local daemon/workspace APIs. |
| Credentials | Saving in send mode made one dry-run mock request; retrieval did not expose the synthetic key. Invalid synthetic key was rejected. This is not an encrypted-storage security audit. |
| Workflow | Full workflow reached the mock and returned accepted with delivery_confirmed=false. Recipient restrictions and dry-run mode were checked separately. |
| Redirect and server failure | HTTP 307 and 503 each produced one mock request and an uncertain result, without automatic retry. |
| Concurrency | Four node runs with one workspace/credential completed. This does not establish isolation between workspaces. |
| Repetition | Explicit repeated execution produced two requests. There is no durable duplicate suppression. |
| Browser | In Chrome, opened an existing workflow, inspected tool fields and retry-off setting, edited its subject, verified autosave/reload, and used Test Run. The mock received the changed subject and the browser showed accepted. |
| Disconnect | Explicit credential deletion prevented further workflow requests. Uninstall then removed the plugin; a database check found zero provider credential rows. Uninstall alone had retained credentials in earlier testing. |

Browser evidence used DOM inspection, persisted draft and mock results; there is
no screenshot record for this check. The workflow was created by the backend
harness, so this is not from-scratch visual authoring acceptance.

## Remaining acceptance

Complete from-scratch editor authoring, model-driven Agent use, Cloud/Enterprise and
published-app sharing permissions, company deployment/timeout/retention controls and authorized provider
validation. Agent repetition and manually rerun workflows can send duplicate mail;
application authorization and reconciliation remain necessary. Company publisher
namespace, developer-agreement review, final artifact checks and Marketplace review
are still required.

The repository's seven serverless protocol scenarios are a separate reproducible
suite. They do not provision a native Dify installation or substitute for the
native results above. The original native harness was tied to a disposable local
Compose environment; the opt-in fixture below replaces those unavailable local paths.

## Two-workspace boundary check

The same exact 0.1.1 archive was installed in two local workspaces with distinct
owner accounts on Dify1.17.1. Native session-authenticated requests showed:

- Workspace B initially listed no credentials from A. With B's own credential
  configured, attempts to update or delete A's credential still failed.
- Foreign workflow read and execution returned404; foreign credential update/delete
  returned400. A workflow in B referencing A's credential ID failed before invoking
  the mock, both before and after B had a valid credential of its own.
- Both owners could invoke their own credential/workflow. Foreign attempts made
  no mock requests and did not delete the other workspace's credential.
- Reverse A-to-B workflow read/run and credential deletion were also denied.
- Both saved credentials were explicitly deleted before uninstall. Execution after
  deletion failed without a mock request. The database had zero remaining provider
  credential rows; the fixture was stopped afterward.

These are backend API checks with synthetic credentials and local HTTPS responses.
Those historical checks did not cover the browser's workspace switcher, every member role
or credential sharing modes. The new backend role checks below cover the five CE roles
and visibility behavior; browser switching, shared app access, Enterprise RBAC, Agent
sessions and Dify Cloud remain untested.

## Local slow-response transport checks

On October 9, 2026, the six cases in `tests/test_transport_timeout.py` exercised
real Requests 2.34.2 and MailChannels SDK 1.5.0 sockets against an ephemeral
loopback HTTP server. Delayed headers and interrupted success bodies returned
`unknown` with the configured dry-run flag, `retry_safe=false` and one POST.
Complete JSON trickled at 0.1-second intervals finished beyond the test's
one-second inactivity timeout, returning `validated` or `accepted` with
`delivery_confirmed=false` for send mode. The helper's requested 30-second timeout
is asserted; only the test transport factory shortens it.

The same suite ran against the safely extracted saved archive identified above;
its runtime files matched source. Response closure was checked for body stalls
and completed responses. Header expiry creates no response object, so that case
checks session closure only. All cases close sockets and join the server and
watchdog. An independent watchdog and a bounded subprocess prevent a missing
timeout from hanging pytest.

These local transport checks do not repeat native Dify validation or exercise
DNS, TLS, connection-establishment stalls, Dify daemon/workflow deadlines or a
strict wall-clock request limit. The saved archive was not rebuilt or changed.
Deployment time limits, model-driven Agent use and publication gates remain open.

## Reproducible native CE role checks

On October 9, 2026, the opt-in [native roles fixture](../tests/native_roles/README.md)
ran the same exact saved archive on Dify Community Edition with `RBAC_ENABLED=false`.
API/worker image `langgenius/dify-api@sha256:53fb08964da7a19d9b9f230a3b2945b6de55dc7b2ec570418e467defa809d82f`
declares core commit `8387590ace4a094de812b7847fc6a4c3a27cd52b` and version 1.17.1.
Daemon image `langgenius/dify-plugin-daemon@sha256:b9d28613f0b4593a6211049251a0d34c5edbb9c1001136a4b24c1e463fd7215c`
is the pinned 0.6.10-local binary; it has no source-revision label. PostgreSQL 16.10,
Redis 8 and Linux ARM64 Python wheels were fixture choices, with image/package
hashes recorded in the generated acceptance report.

| Native CE role | Masked credential list | Add/update/delete/default | Draft read/save, node and full workflow |
| --- | --- | --- | --- |
| Owner | Visibility filtered | Allowed | Allowed |
| Admin | Visibility filtered | Allowed | Allowed |
| Editor | Visibility filtered | 403 | Allowed |
| Normal | Visibility filtered | 403 | 403 |
| Dataset operator | Visibility filtered | 403 | 403 |

The completed matrix passed 80 recorded native cases and made 19 synthetic POSTs.
Saving or changing complete credentials always made one dry-run validation request,
even in send mode. Name/default/delete operations made none. Every denied mutation
preserved the complete independently scoped credential row hash/count, including
private rows absent from the owner's ordinary list. Denied draft writes preserved
the graph and made zero requests. Each owner/admin/editor node and full workflow
returned `accepted` with `delivery_confirmed=false`, using the expected configured
sender, recipient and send mode, checked through fixture labels and routing hashes.

Omitted visibility became `all_team_members`. `only_me` ordinary listings included
only the creator's private credentials and shared rows; admin had no private-list
bypass. Explicit included IDs returned masked borrowed metadata with
`from_other_member=true`. Editor execution using the owner's private credential ID,
and execution with an omitted ID using the owner's private default, both succeeded.
Owner/admin mutation gates allow another creator's same-workspace private credential
to be renamed or deleted. `only_me` is list visibility on this pinned CE runtime,
not a workflow execution isolation guarantee.

Configured workspace B could execute its own credential. A foreign A credential ID
in B's graph failed with zero requests, even with B configured. Foreign workflow
read/node/full execution returned 404 `app_not_found`; foreign credential
update/delete/default returned 400 `invalid_param`, without changing A's rows.
Switching one editor from A to B changed the active role to normal and denied B's
draft/node access with 403; switching back restored successful A execution. An
unjoined switch returned 403 `account_not_link_tenant` with unchanged active context.
These are authenticated backend HTTP checks, not browser switcher acceptance.

Native containers used only an internal Docker network, with no published ports.
Docker Desktop suppressed the planned host binding, so the fixture used real
localhost HTTP inside the API container through a bounded stdio broker. Native
cookies, CSRF and authorization decorators remained active. Before credentials,
native DNS/TLS and blocked external egress were checked; after installation,
default Requests TLS verification and empty proxy settings were checked in the
actual plugin interpreter. No provider, model, SMTP or Marketplace service was used.

Explicit credential deletion blocked previously runnable workflows without a mock
request. Native uninstall removed both inventories, and an independent scoped
DB query found zero provider rows. Owned containers, networks, volumes and generated
secrets were removed; prior unrelated running containers were preserved. A deliberate
precredential failure also proved teardown with zero requests. Earlier failed setup
and partial matrix attempts remain failed evidence, including permission, seeding,
response-schema, mock-file and missing worker-queue corrections. They do not count
as acceptance. Native CLI locale/process cleanup warnings and PostgreSQL daemon
first-connection database creation messages do not establish broader compatibility.

The fixture does not validate browser authoring, Agent/model use, Cloud, Enterprise
RBAC, published-app sharing, real delivery, deployment retention/deadlines, native
workflow timeout behavior, a rebuilt final artifact or publisher/Marketplace gates.
The existing 44 default tests and seven packaged protocol scenarios were reused;
this tests/docs-only change ran opt-in native checks and offline fixture checks.
