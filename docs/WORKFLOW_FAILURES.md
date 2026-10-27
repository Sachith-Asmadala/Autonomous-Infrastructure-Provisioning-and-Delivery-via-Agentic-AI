# Workflow failures

The page lists saved GitHub Actions failure records. It does not invent runs
from a failed local command or a general diagnosis request.

## Load existing runs

1. Open **Workflow Failures → Import failures → Load from GitHub**.
2. Enter the repository as `owner/repository`.
3. Select **Load failed runs**.

The app imports the ten most recent failed or timed-out runs. Public run
metadata can be read without credentials. Private repositories and automatic
log downloads need a configured GitHub token or an active GitHub App
installation with Actions read access. Log-download errors are shown beside
the run; the failed run remains visible even if diagnosis cannot complete.
Repeated imports by the same account reuse saved records.

## Diagnose pasted logs

Expand a run and choose **Paste run logs**, or choose this method in the import
dialog. Supply its GitHub Actions run URL and the failed job's logs. The trained
model supplies a diagnosis and recommendation, which are saved to the page.
This path works without GitHub or LLM credentials. Logs are cleaned and token,
password, and connection-string patterns are redacted before storage.

Admins can see all saved failures. Developers can see only their own imported
records and can request fix PRs for these records. Webhook and legacy records
remain visible to admins. Separate accounts may import the same GitHub run;
**Recorded by** identifies each workspace record's owner.

## Fix pull requests

**Request fix PR** creates an approval request. Every repository change waits
for an explicit human decision, including low-risk fixes. Developers may review
only their own authorized work; admins may review all work. Repeated requests
reuse an unexpired pending approval. Expired approvals cannot execute; refresh
the failures list to request a new review. Actual
execution requires configured GitHub access and uses a branch and pull request.

## Automatic webhook imports

Configure the GitHub webhook URL as `/api/v1/webhooks/github` on a backend that
GitHub can reach. Subscribe to workflow run completion events and configure a
matching webhook secret. Failed and timed-out completed runs are stored even
when logs cannot be downloaded. A local backend without a public webhook URL
will not receive events; use manual imports to load historical failures.

## Verification

Run `make test-backend`, `make lint`, and `make build`. Tests cover account
ownership, public metadata imports, repeat imports, pasted-log diagnosis,
installation-token access, invalid input, unavailable services, and mandatory
approval before GitHub writes. Live log downloads and PR execution additionally
require valid GitHub credentials; LLM chat requires its configured provider.
