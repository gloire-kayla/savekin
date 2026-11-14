# SaveKin

Web and native Android/iOS development clients for trusted savings groups. Shared goals, paid shares, member-approved rules, and separate president/treasurer responsibilities.

## Start testing

Run the backend in one PowerShell terminal:

```powershell
.\start.ps1
```

Open http://127.0.0.1:8000 on this computer. Create an account with **test details and a unique test password**. All financial actions are demo or sandbox only. The server binds to loopback; it is not a production deployment.

### 60-Second Quick Demo for Judges & Reviewers
1. Run `.\start.ps1` (or `python server.py`) and open http://127.0.0.1:8000.
2. Sign in or register with any test email and password.
3. Click **"✨ Load Sample Circle"** on the dashboard.
   - Instantly populates an active savings circle with pre-existing members (Alice as President, Bob as Treasurer, Charlie as Member).
   - Pre-configured with active contributions, catch-up arrears, discussion messages, and settlement ready for review!
4. Open the **SaveKin Helper** (AI assistant) via the floating chat button to ask budgeting, cycle comparison, and rule questions.

### USB Android

1. Connect and unlock the phone; accept its USB debugging authorization prompt.
2. Keep the backend running.
3. In a second terminal run:

```powershell
.\test-phone.ps1
```

This forwards device ports 8000 and 8081 to this computer and starts the native app through Expo Go. Expo Go 58 is required for the current Expo SDK 58 project. Dependencies are recorded in `mobile/pnpm-lock.yaml`; to reinstall, use pnpm in `mobile/`. Node 22.13+ is required.

For the **web app on the phone**, run `test-phone.ps1 -WebOnly`, then open http://127.0.0.1:8000 in the phone browser. This is a responsive web client; the Expo project is a separate native client sharing the same API.

The phone API address is `http://127.0.0.1:8000` over USB forwarding. An Android emulator without forwarding can use `EXPO_PUBLIC_API_URL=http://10.0.2.2:8000`. Do not open this development server to Wi-Fi or the internet. Neither store binaries nor production hosting are configured yet.

## Implemented workflows

- Registration/sign-in, salted scrypt password hashes, expiring server-side sessions, logout, and per-group authorization.
- Browser sessions use an HttpOnly, SameSite cookie. Native tokens are held in memory; the mobile app asks you to sign in after a restart.
- Group creation with accepted founding rules. The creator is president; a different active member must be elected treasurer.
- Private invitation links, a rule preview, explicit acceptance, and group membership.
- Initial members can join before funding begins. Once contributions start, late joiners wait for the next cycle by default, or catch up elapsed months if the accepted rules allow it.
- USD or RWF group ledgers. RWF accepts whole francs. Currency is fixed per group. Sandbox checkout supports USD only.
- Monthly share commitments, due amounts, arrears, contribution credit, increases with elapsed-month catch-up, and next-cycle share changes.
- Optional collected fines, demo expenses, early-exit requests and penalties.
- Member votes for rule/leadership changes. Current default requires **two-thirds of the eligible active membership to vote yes**; this is explicitly shown before joining. The nominee must consent by voting yes. Voting membership is snapshotted when a proposal is created. One member has one vote; the same member cannot vote twice.
- Separate president and treasurer approval of exits and cycle settlement.
- Goal-ending, date-ending, and repeating cycles. Reaching a goal pauses new savings but allows members to clear existing arrears.
- Principal plus share-weighted surplus allocation, or surplus carry-forward. Integer largest-remainder rounding preserves every cent / whole franc.
- Frozen settlement snapshots; simulated distribution; explicit start of the next repeating cycle after distribution.
- JSON ledger export on web and a group action audit trail in the API.
- Native screens for the same group, share, vote, exit, and settlement workflows.

## First test journey

1. Register as the president and create a demo group. Use a first cycle end date of today to exercise settlement.
2. Copy the invitation from the group. In a different browser profile or on the phone, register a second test user and accept the invitation **before recording contributions**, so both are active this cycle.
3. President: Rules → Propose an officer → nominate the second member as treasurer.
4. Both members: Decisions → vote yes. Roles must be separate.
5. Each account records its own demo contribution. Try increasing shares and inspect the added arrears.
6. Once all members are fully paid and the goal/date condition is met, either officer proposes settlement.
7. Both officers explicitly approve it. Missing, numeric, or text approval values are rejected by the API; a repeated approval cannot count as a second officer. Either officer can reject the pending settlement to reopen the cycle. The treasurer can then simulate the distribution; **this sends no money**.
8. For a repeating group, the president starts the next cycle. Scheduled share changes and waiting memberships take effect.

## Accounting rules in this version

- One share has a fixed monthly price for a cycle. Changing its price mid-cycle is blocked.
- Increasing shares now adds the incremental contribution for every elapsed monthly period, including the current one. It creates arrears until actually paid.
- Decreases apply next cycle. An early departure instead follows the exit process.
- Extra money is contribution credit; it does not silently buy more shares.
- Early-exit requests freeze that member's contributions while under review. Officers hand over their role before leaving.
- An exiting member receives principal less the accepted fixed penalty, capped at their principal, without a share of cycle surplus. The request and settlement are still simulated.
- Only fully paid active members can be included in the end-of-cycle allocation. Resolve all active arrears and pending governance/exits before settlement.
- Expenses that consume principal block the current full-principal settlement; loss allocation requires a future explicit rule rather than silently reducing entitlements.
- Fines are optional manual **collected** demo entries, not automatic debits or a complete overdue-fine scheduler.
- Monthly periods are calendar-month buckets beginning with the cycle's start month. This is explicit development behavior, not a daily interest calculation.
- There is no guaranteed yield. Surplus comes from collected group funds after recorded outflows. Loans are later scope.
- The ledger is not proof of a treasurer's available PayPal funds and does not prevent withdrawals outside SaveKin.

## PayPal sandbox

Set process environment variables before starting the server. `.env.example` is documentation and is not automatically loaded:

```powershell
$env:PAYMENT_MODE = 'sandbox'
$env:PAYPAL_CLIENT_ID = '<sandbox client ID>'
$env:PAYPAL_CLIENT_SECRET = '<sandbox client secret>'
$env:PAYPAL_TREASURER_EMAIL = '<sandbox recipient email>'
.\start.ps1
```

Only the configured sandbox recipient is supported. The group's declared treasury receiving email must match it, and the credentials must authorize that recipient. The treasurer's SaveKin login email can be different. Existing installations fall back to the original login email until the treasurer declares the receiving account. Merely entering a name or email does not connect a PayPal account. Production multi-treasurer onboarding and approval for the intended savings use case remain outstanding.

Web checkout creates and captures orders server-side. Capture must confirm the expected status, amount, USD currency and recipient. The contribution is scoped to the authenticated payer, group, cycle and order. Stable capture request IDs and unique references prevent duplicate ledger credit.

Actual returned PayPal fees are disclosed separately; only net funds count as the sender's savings contribution. An interrupted captured payment can now be recovered from PayPal order details. Verified sandbox webhooks reconcile completed, pending, refund and reversal events idempotently. Provider fees and refund debits remain separate, append-only ledger records. Unknown fees, ambiguous reversal/refund combinations and late changes to distributed cycles block settlement for review. This is transaction reconciliation, not PayPal account-balance reconciliation. No real sandbox credentials were supplied; automated payment checks mock PayPal, not an actual provider transaction.

Native sandbox payments open a browser checkout through a 90-second, single-use handoff code. The code is hashed in storage, removed from browser history before exchange, and consumed atomically. The browser receives its own HttpOnly session; return to the app to refresh automatically. Checkout remains browser-based, not embedded in a native WebView.

Approved sandbox cycle distributions now use PayPal Payouts. Every recipient saves a sandbox destination in Payment settings before proposal; both officers approve a frozen statement including destinations. Only the configured treasurer can initiate payouts. Requests are journaled before contacting PayPal, use a fixed sender batch ID, and cannot be replaced automatically. Pending/unclaimed/failed items prevent completion. A treasury allocation remains in the treasury account and is shown as retained. Payout fees are paid separately by the treasurer and do not reduce the approved member allocations. Failed or ambiguous items require review; there is no automatic per-item resend. Signed payout webhooks and explicit status checks reconcile items. Sandbox payout requests are coded and mock-tested; a real sandbox payout still requires account access and an end-to-end provider test.

## First real sandbox checkout

If Windows blocks `.ps1` files, use the Python launcher instead. No execution-policy change is needed:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\start_sandbox.py --restart-local
```

Use `--check-only` to validate credentials without restarting anything. The launcher prompts for the secret with hidden input, checks sandbox authentication, and only then replaces a verified local SaveKin backend. Credentials are passed through the process environment, never command-line arguments or a saved file.

1. In [PayPal Developer](https://developer.paypal.com/dashboard/), open **Apps & Credentials**, choose **Sandbox**, and create a Merchant app associated with your sandbox Business account. Keep the client ID and secret on your computer. [Official credential instructions](https://securepayments.paypal.com/us/cshelp/article/how-do-i-create-paypal-rest-api-credentials-ts1949).
2. Under **Testing Tools → Sandbox Accounts**, identify the Business recipient and a separate Personal buyer. These are simulated accounts, separate from your real PayPal login. [Official sandbox account guide](https://developer.paypal.com/sandbox-testing/accounts).
3. For this one-recipient development integration, create a SaveKin test treasurer account using that sandbox Business email. Invite it to a test group before funding starts, nominate it as treasurer, and approve the nomination with both members. Your app credentials must authorize the same sandbox Business recipient.
4. Run `start-sandbox.ps1 -RestartLocal` in your own PowerShell terminal. Enter the client ID, Business email, optional webhook ID and hidden secret. The webhook ID can be left blank for the first browser checkout.
5. Sign in to the web app as the contributing member, choose a USD group, and select PayPal sandbox contribution. Use the **Personal sandbox buyer** login in PayPal’s approval window. Confirm the net contribution and separate fee entry after capture. Never enter your real PayPal buyer credentials in the sandbox approval window.
6. Recheck the order from the group ledger and verify the contribution remains recorded once. Refund and webhook testing comes after the HTTPS listener is configured.

## Payment recovery and sandbox webhooks

Both clients show PayPal order history under the group ledger. **Check payment status** retrieves an existing order without charging it. An approved, uncaptured order can be finished explicitly in the client; checking status never captures automatically. Late completion or refunds invalidate pending/approved settlement snapshots. Updates to already-distributed cycles require reconciliation and block further settlement.

To configure credentials locally and replace the verified running development server only after authentication succeeds, run:

```powershell
.\start-sandbox.ps1 -RestartLocal
```

Use `-CheckOnly` instead to test credentials without stopping or starting a server. Without either switch, an already-running server is left untouched and setup stops.

The script prompts for a sandbox client ID, hidden secret, recipient email and optional webhook ID. It makes only an OAuth authentication request before starting the backend; it does not create a payment. Invalid credentials leave the existing app running. Values are kept in the server process environment and restored on exit; they are not written to disk. Do not paste secrets into chat or source files. It does not create a PayPal app or connect arbitrary treasurers.

The listener is `POST /api/paypal/webhook`. It validates every delivery through PayPal’s verify-webhook-signature API using `PAYPAL_WEBHOOK_ID` plus the PayPal transmission headers. Unverified deliveries cannot change the ledger. Event IDs and provider references prevent duplicate credit or deductions. Failed processing is not marked completed, so a delivery can be retried. No incoming resource URLs are fetched directly.

PayPal must reach an HTTPS listener, so the loopback server alone cannot receive provider deliveries. Before actual webhook testing, configure a controlled HTTPS endpoint forwarding only the webhook route; do not publish this development server. Subscribe the sandbox app to CHECKOUT.ORDER.APPROVED and PAYMENT.CAPTURE.COMPLETED, PENDING, DENIED, REFUNDED and REVERSED. PayPal simulator mock events cannot use postback signature verification; use actual sandbox app events. No public endpoint has been provisioned by this change. See [PayPal’s webhook integration guide](https://developer.paypal.com/api/rest/webhooks/rest/).

Recovery supports the one-order / one-purchase-unit / one-capture contract created by this app. Completed refund details determine the merchant’s actual net debit. Gross refund amounts are retained as memo records, not double-counted as cash outflows. A full refund can leave an unrecovered fee and a negative pool; SaveKin preserves that loss rather than manufacturing funds. Refunds after reversals and changes after a member’s exit require manual review. This version blocks affected settlements and deliberately provides no button to erase review holds. A full operational review workflow remains future work.

The handler never initiates refunds, real payouts or live transactions. Provider calls are mocked in automated tests. Actual sandbox credentials and actual webhook delivery still need to be tested.

## Optional SaveKin helper chat

Both clients include a conversational helper for onboarding, product/rule questions, troubleshooting, choosing a savings purpose, comparing goal/date/repeating cycles and drafting goals, objectives and roadmaps. It works before creating a group. Select a group to include its accepted rules and the current member's numeric account totals; general planning sends no group records.

Configure server-side `OPENAI_API_KEY` and `OPENAI_MODEL`, or use `start_sandbox.py --restart-local --with-ai`. No provider key/model or paid request is selected automatically. No actual AI call has been demonstrated in this workspace.

Conversations are stored in the local SaveKin database per authenticated user and can be reopened or deleted on web and mobile. The last 12 saved messages accompany each follow-up. Conversation ownership and group membership are checked server-side; client-supplied history is ignored. Concurrent replies cannot append against stale history. A shared chat is not automatically visible to other group members.

The user explicitly consents to sending their message, recent chat history and limited selected-group context. Automatic context excludes names, emails, invitation links, supporting evidence, credentials and other members' individual records. Anything typed in messages is also sent. The OpenAI adapter uses `store:false`; this is not a promise of zero provider retention. The Elastic adapter uses Agent Builder and may retain provider-side conversations. Generated replies are escaped as text on web. AI has no tools: plans are drafts, and it cannot edit records, approve decisions, create groups, or move money. `SAVEKIN_HELP.md` is the product knowledge supplied on every turn. Without configuration the interface says unavailable rather than simulating answers.

Provider calls and isolation are mock-tested. Implementation follows [official OpenAI conversation-state guidance](https://developers.openai.com/api/docs/guides/conversation-state).

The web layout keeps the full labeled sidebar on desktop. Collapse menu hides it entirely; Menu opens a labeled drawer on smaller screens, with overlay dismissal, Escape and keyboard focus handling. No icon-only navigation rail is used.

## Validation

```powershell
python -m unittest discover -s tests -v
```

On this computer the Python executable used by `start.ps1` is `C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/python.exe`. Python 3.11+ works; no third-party backend dependencies are needed.

Critical tests cover authorization/isolation, accepted invitations, waitlists, catch-up shares, voting, distinct roles, exits, surplus rounding, carry-forward, double approval, cycle transitions, and payment verification/idempotency.

Native bundle validation:

```powershell
cd mobile
pnpm exec expo export --platform android --output-dir dist-test
```

## Structure and remaining work

- `savekin.py`: authenticated API, domain rules, settlements, PayPal sandbox integration.
- `server.py`: shared SQLite/PayPal helpers and server launcher. Legacy prototype helpers remain for regression tests.
- `web/`: responsive browser client with the blue/apricot SaveKin palette.
- `mobile/`: Expo SDK 58 native client.
- `tests/`: isolated temporary-database tests.
- `data/gathersave.sqlite3`: ignored local database. Original prototype tables are preserved; they are not silently assigned to a newly registered user. New authenticated data uses separate `sk_` tables.

Still required for the full product: live testing of the optional AI assistant, live/approved treasurer onboarding and payouts, complete fee/refund reconciliation, production webhook deployment and manual review tooling, email verification/recovery, secure persistent mobile sessions, broader rule configurability, reminders, production HTTPS/hosting, backups, and real device testing of every workflow. No real money should be used in this local build.

## Final review build

See [DEMO_REVIEW.md](DEMO_REVIEW.md) for the combined review path, setup commands, verified behavior, and remaining external integrations. `start_sandbox.py --restart-local --with-ai` optionally prompts for an AI key (hidden) and model ID without saving either. `webhook_setup.py` registers capture and payout notifications for an existing public HTTPS relay; it does not create that relay or expose the whole app. Multi-treasurer partner onboarding, production hosting, live funds, loans and automated sandbox early-exit payouts remain outside this build.

## Elastic managed AI option

See [ELASTIC_SETUP.md](ELASTIC_SETUP.md). Create/check the dedicated helper with `elastic_setup.py`, then launch with `start_sandbox.py --restart-local --with-elastic`. Keys are prompted locally and not saved. Agent access is checked before restart. Elastic is a server-side alternative to OpenAI, not an automatic fallback. No real Elastic reply has been tested without account credentials.


## Profiles, discussions and handovers

The sidebar name/avatar opens My profile. Members can update names and PNG/JPEG photos (128 KB), verify/change their sign-in email, change passwords, and set a separate payout destination. Email changes require the current password plus a code sent to the new address. Password changes revoke other sessions; recovery revokes all sessions. Verification codes expire after 15 minutes and five incorrect attempts; recovery codes are single use.

Configure SMTP environment variables from `.env.example` before starting the server. TLS is required. Without delivery setup the interface clearly reports that verification/recovery email is unavailable. For local testing only, add `--local-mail` to the Python launcher (or set `$env:SAVEKIN_MAIL_MODE='local'` before starting it): development emails are saved as `.eml` files in `data/mail-preview/` (or beside the configured database). These contain private codes; they are ignored by git and never served by the web server. No email is sent in local mode. Open the newest preview locally to copy the code; do not share it.

Group Discussions supports text messages, pagination, unread indicators and retries without duplicate messages. Current members can read; members who have left cannot access discussions. Sender names are retained as they were when messages were sent. Messages never count as votes. Notification and discussion updates poll every 15 seconds while the relevant client is active; these are in-app notifications, not push or email reminders.

Both the floating chat shortcut and the menu open the dedicated SaveKin helper screen. Group selection and unsent helper/discussion drafts survive screen navigation within the current session, and are cleared on logout. Mobile photo selection uses [Expo ImagePicker](https://docs.expo.dev/versions/v58.0.0/sdk/imagepicker/).

A voted treasurer replacement starts a handover and keeps the outgoing treasurer in office. Contributions, distributions, joins and financial/group changes pause. The nominee declares a sandbox receiving account. The outgoing treasurer reconciles pending orders/payouts and submits a statement whose available group funds match the recorded pool. At least two-thirds of active members, including the president and both treasurers, approve the statement and fee payer. Revising it clears approvals. The outgoing treasurer records an external transfer reference; the incoming treasurer and president independently confirm. No funds are transferred by this workflow and no manual confirmation is labelled PayPal-verified.

Sandbox activation also requires server configuration for the incoming account. Reconcile all old-account payments before restarting with the incoming account's sandbox credentials. The ledger, shares and original payment recipients remain unchanged. Production merchant onboarding and automatic treasury transfer are not implemented; entering an email never grants access to an account. A refusal to transfer or an unresolved difference keeps the handover pending.

## Render free demo

The repository includes a Render Blueprint in `render.yaml`. To create the free web service, sign in to Render, choose **New → Blueprint**, connect this GitHub repository, and apply the `savekin` service. Render will build and deploy it at an `onrender.com` address. The service runs in demo-payment mode by default.

The free web service sleeps after 15 minutes without traffic, so its first request after inactivity may take a little while. It has an ephemeral filesystem: the SQLite database can be lost when the service restarts, sleeps, or redeploys. Use only test accounts and disposable demo data; do not use this deployment for real savings or production. This configuration does not create a Render Postgres database. Render's separate free Postgres plan has a 30-day expiration, so that deadline does not apply to this SQLite-based demo.

To enable external integrations, add their credentials as secret environment variables in the Render dashboard; never commit them to this repository. PayPal Sandbox requires `PAYMENT_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `PAYPAL_TREASURER_EMAIL`. Elastic AI requires `AI_PROVIDER=elastic`, `ELASTIC_KIBANA_URL`, `ELASTIC_API_KEY`, and `ELASTIC_AGENT_ID`. Do not enable a provider until its credentials are configured and the deployed integration has been tested. The free service may sleep during provider setup or review.
