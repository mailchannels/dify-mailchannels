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

Complete from-scratch editor authoring, model-driven Agent use, cross-workspace
permissions, company deployment/timeout/retention controls and authorized provider
validation. Agent repetition and manually rerun workflows can send duplicate mail;
application authorization and reconciliation remain necessary. Company publisher
namespace, developer-agreement review, final artifact checks and Marketplace review
are still required.

The repository's seven serverless protocol scenarios are a separate reproducible
suite. They do not provision a native Dify installation or substitute for the
native results above. The original native harness was tied to a disposable local
Compose environment; a portable native fixture remains useful future work.
