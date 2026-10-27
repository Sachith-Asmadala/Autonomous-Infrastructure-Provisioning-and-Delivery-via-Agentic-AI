# Workflow pull requests from Repositories

## Normal flow

1. Open **Repositories**, enter `owner/repository`, and choose **Scan Repository**.
2. Review the detected stack and readiness results.
3. Choose **Create Workflow PR**. This saves a human approval request; it does not send the PR yet. Repeated submissions reuse your unexpired pending request for the same repository and replacement option.
4. Open **Review approval**. A developer can approve their own authorized work; an admin can review all members' requests. Review the repository and replacement option before approving.
5. After approval, execution creates a branch, commits the workflow, and opens a PR. Use **Open PR** to view it on GitHub. The application never merges the PR automatically.
6. Return to Repositories to see the saved result. Pending requests refresh periodically and when the window regains focus; **Refresh PR status** also checks the latest outcome. The link after an approval opens that specific request, including when an admin reviews a developer's work.

Workflow writes always require review, including when `ENABLE_HITL=false`.

## Connect GitHub before the real demo

Configure GitHub access privately in `backend/.env`, then restart the backend. Use either:

- `GITHUB_TOKEN` for a local demonstration. The token must have access to the target repository and permission to create branches, edit workflow files, and create pull requests.
- A GitHub App with `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY`, installed on the target repository and recorded through this application's existing installation flow.

For a fine-grained token or App, grant **Contents: write**, **Workflows: write**, and **Pull requests: write** on the target repository. A classic token needs `repo` and `workflow` scopes for this workflow-file flow. See GitHub's [file creation permissions](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents) and [pull request permissions](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

The integration indicator checks whether backend credentials exist; it does not certify that a token is valid or authorized for a particular repository. Repository scanning and execution report permission or authentication errors separately. Never paste credentials into chat, commit `.env`, or add tokens to the frontend.

## Common results

| Result | What to do |
| --- | --- |
| Approval Required | Review and approve the saved request before expecting a GitHub PR. |
| GitHub access is not connected / token not configured | Configure backend GitHub credentials and repository access first. |
| Authentication or permission error | Check token validity, selected repository, organization approval/SSO rules, and workflow-writing permissions. |
| Existing AI-generated workflow file | Review the existing file. Select **Replace existing AI-generated workflow file in the pull request branch**, then request and approve a new review if replacement is intended. |
| Generated workflow already matches the default branch | There is no change to propose. A new PR is unnecessary; no branch is created for this case. |
| Request failed | Read the error, resolve its cause, then choose **Request a new review**. Failed execution is never displayed as PR creation. |
| Request timed_out / rejected | Choose **Request a new review** if the work is still needed. Expired or rejected requests cannot execute. |
| Pull Request Created | Open the linked PR and inspect its changes. A workflow merged later must differ before another update PR is useful. |

If GitHub rejects a write after branch creation, that branch may remain. A retry uses a distinct branch name; the application does not delete branches automatically.

## API status lookup

`GET /api/v1/repositories/workflow-pr-status?repo_full_name=owner/repository` returns your latest request for the default replacement option, or `null` when none exists. Set `overwrite_existing_workflow=true` to inspect replacement requests.

Use `approval_id=<uuid>` to inspect a specific request. Members can only inspect their own requests; admins can inspect a member's request by ID. An inaccessible or mismatched request returns 404. Completed results include `pull_request_url`; failed results include a sanitized error in `message`.

`GET /api/v1/repositories/integration-status` returns only `credentials_configured`; it never returns credential values.
