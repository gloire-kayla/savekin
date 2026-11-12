# SaveKin combined review build

SaveKin helps trusted groups agree on rules, contribute by shares, see the same ledger, approve decisions and distribute savings. Funds are held by the configured sandbox treasurer, not a SaveKin wallet. This build is local development and sandbox only.

## Start the updated build

Stop the existing server with Ctrl+C, then run this from the project directory:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\start_sandbox.py --restart-local
```

Use the same working US Business sandbox app credentials and Business email. Leave Webhook ID blank if no public endpoint is configured. Keep the terminal running. Open http://127.0.0.1:8000 and refresh with Ctrl+F5. Existing accounts, groups and ledger records remain available. New database tables are added without replacing existing records.

On Android, reconnect USB, authorize debugging if prompted, and forward ports 8000 and 8081 using the existing phone script. Open SaveKin in Expo Go. This is an Expo development app, not a signed Play Store release. An Android bundle is exported under `mobile/dist-test` for build verification.

## Review once, in this order

1. **Accounts and groups:** sign in, use Payment settings or Sign out at the top of the web app, create a USD group and invite a separate treasurer. On mobile, Payment settings is on the overview screen.
2. **Rules and governance:** appoint the treasurer through Rules → Propose an officer, then Decisions. The nominee consents and the member vote must reach the two-thirds threshold. Show the goal/date, shares, optional fines, exit penalty and surplus policy.
3. **Contributions:** pay through the existing working Personal sandbox account. Check the contribution, separate PayPal fee, arrears and recorded pool. A net contribution below the monthly obligation leaves arrears; provider fees are not fabricated as savings.
4. **Mobile checkout:** select Pay with PayPal sandbox. A 90-second single-use link opens a browser session for the same SaveKin member and group, without copying a bearer token into the URL. Approve with a Personal sandbox PayPal login. Return to the app; it refreshes when active. The browser checkout is deliberate, not an embedded native payment screen.
5. **Payout destinations:** before proposing settlement, each recipient saves a sandbox PayPal email they control in Payment settings. This is a declared destination, not verified account ownership. The treasury member can use the configured Business email; that allocation is retained rather than sent to itself. Both officers review the frozen destinations in the settlement proposal.
6. **Settlement:** reach the group goal or end date, clear all active arrears and resolve pending governance/exits/payment reviews. Propose settlement, review allocations and destinations, and obtain explicit approval from both officers. For a separate quick demo group, an end date of today lets you exercise the settlement flow without changing an existing group's rules.
7. **Sandbox distribution:** sign in as treasurer and choose Settlement → Send approved sandbox payouts. Confirm sender-paid provider fees. The app sends the saved batch once, and shows recipient statuses. Check distribution status retrieves the same batch. Pending, unclaimed, blocked or failed items keep the cycle unfinished. Resume same sandbox batch reuses the original request after an uncertain outcome; it never creates a replacement batch. Do not make separate manual replacement payouts for uncertain items.
8. **Next cycle:** a repeating group unlocks the next cycle only after all outbound payout items are confirmed successful. Treasury allocation is labeled retained. Carried surplus transfers to the new cycle. Later refunds or returned payouts require reconciliation.
9. **AI assistant:** after configuration below, ask why you owe catch-up contributions or how the accepted surplus rule works. The assistant explains supplied records, cannot approve decisions or move money, and requires explicit data-sharing consent.

## External setup still needed

### PayPal Payouts

The code is integrated with the sandbox Payouts API, but this session has not sent an actual provider payout. Check that Payouts is enabled/available for the working Business sandbox app, and that its sandbox balance covers the approved allocations plus payout fees. The test treasurer bears payout fees separately; fees are not silently subtracted from approved member amounts. [PayPal prerequisites and API workflow](https://developer.paypal.com/api/payouts).

If PayPal denies access, resolve that capability with PayPal. A successful OAuth authentication check alone does not prove Payouts access. Failed/uncertain batches remain visible; per-item automatic retries and manual reconciliation clearing are intentionally absent.

### Optional AI

No AI API key was provided during this build. The assistant endpoint and consent flow are implemented and mock-tested; no real provider response was tested. To activate it, create an API key in your own OpenAI project and select a model available to that project, following the [official OpenAI quickstart](https://developers.openai.com/api/docs/quickstart).

Restart with:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\start_sandbox.py --restart-local --with-ai
```

The launcher asks for the key with hidden input and the model ID. Both stay in process memory/environment and are not saved to disk. Do not put an API key in web/mobile source, `EXPO_PUBLIC_` variables, or chat. Payment settings shows whether AI configuration is present. Actual AI operation remains unverified until a real response succeeds. For an AI hackathon submission, do not claim this has been demonstrated before configuring it.

### Optional signed webhooks

Localhost cannot receive PayPal's remote notifications. Provide a public HTTPS relay exposing only `/api/paypal/webhook` to the local backend; do not expose all development routes. No public relay or deployment was provisioned in this session.

Then run:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\webhook_setup.py
```

Enter the HTTPS URL and the same sandbox app credentials locally. The tool registers capture and payout events, prints the Webhook ID, and avoids duplicate URL registration. Restart SaveKin and enter that ID. Incoming notifications are verified with PayPal, then trigger provider status reads; an incoming event alone is never treated as proof of payment. Existing registration events can instead be updated in the Developer Dashboard. [Official payout event names](https://developer.paypal.com/payouts/webhooks/).

Without this external setup, explicit payment/distribution status checks still work. Having only a Webhook ID does not prove delivery works.

## Evidence and limits

- You completed an actual US sandbox contribution and confirmed shared ledger visibility across members and treasurer.
- Automated tests use isolated databases and mocked provider responses, not actual money or new PayPal transactions. They cover approval boundaries, share allocations, duplicate prevention, interrupted payouts, frozen recipients, partial failures, signed notification replay and mobile handoff expiry/replay.
- JavaScript syntax and mobile JSX are checked; an Android production JavaScript bundle exports successfully. No iOS native build or signed Android package was produced.
- The Windows visual automation helper was unavailable, so the new screens still need a visual review. A successful bundle does not establish usability on every device.
- Real PayPal payouts, public webhook delivery and actual AI responses require the external setup above and remain unverified.
- Multi-treasurer PayPal OAuth onboarding needs an approved platform integration; this build supports one locally configured sandbox treasury app. Email matching is not an account ownership guarantee. [PayPal platform access requirements](https://developer.paypal.com/platforms/get-started/).
- Live funds, loans, production deployment, password recovery/email verification, automatic early-exit PayPal payouts and production compliance remain outside this build. Early-exit rules/approvals and demo completion remain available; sandbox exit payout is blocked rather than marked paid.

## A short demo narrative

“Trusted savings groups often keep fragmented records. SaveKin gives members agreed rules, share-based contributions and a shared ledger. Here a member pays through PayPal sandbox and everyone sees the confirmed net contribution. Officers approve an exact settlement, and the treasurer can initiate sandbox distributions with visible per-recipient status. The optional AI assistant explains the member's own records with consent; it never controls the funds.”

Only include payout or AI footage after those provider flows have actually succeeded. Show one complete group journey; use the mobile screen to demonstrate the same shared records.

## Treasury contributions and fee estimates

The treasurer can choose **Contribute treasury funds** in their group. Enter their own amount already set aside in the treasury, a unique supporting reference and an explanation. The web app also accepts an optional PNG/JPEG/PDF attachment up to 256 KB. Mobile accepts the reference and explanation; file attachment/download uses the web app. No transfer is made by this request.

The separate president opens **Decisions**, reviews the reference/note and optional evidence, then approves or rejects. Only approval credits `treasury_contribution` to the treasurer and pool. The ledger labels it **Manually confirmed treasury contribution**; it is never presented as a provider-verified transfer. Duplicate confirmation and reused accepted/pending references are rejected. Pending requests block settlement and officer changes. This is a trusted-group declaration and review, not independent evidence of available PayPal balance or a prevention of treasury withdrawals.

For ordinary sandbox checkout, enter **Amount to save**, then **Calculate total**. The quote shows target savings, estimated fees and gross checkout amount before PayPal approval. The default sandbox example is 3.49% + USD 0.49, configurable through process variables `PAYPAL_FEE_BPS` and `PAYPAL_FEE_FIXED_CENTS`. It computes the fee on the final total and rounds in cents: under that example a USD 4.00 target needs USD 4.65 gross, with an estimated USD 0.65 fee. Merely adding the original USD 0.63 fee to USD 4.00 would not cover the percentage increase. [Published US Checkout fee example](https://www.paypal.com/us/business/paypal-business-fees).

Quotes are bound to the signed-in member, group, cycle and amount, expire after ten minutes, and reuse the same returned order on repeat submission. Actual fees may differ by account/payment route; only actual confirmed net becomes savings. The payment result reports a shortfall if one occurs; extra net remains savings credit. The app never silently charges a second payment or manufactures the requested savings amount. This estimator is a sandbox demonstration, not an approved live fee policy; PayPal's US agreement restricts payment-method surcharges. [US agreement](https://www.paypal.com/US/legalhub/paypal/useragreement-full?locale.x=en_US).

## What to review in the helper chat

Use **SaveKin helper** in the web sidebar or mobile overview for general onboarding and planning, even before joining/creating a group. In a group, **Ask savings assistant** opens group context with your own totals and the accepted rules. The helper is a full chat with follow-up replies, saved private conversations, New chat and Delete chat. The web context selector can start a separate general or group conversation.

Try this conversation:

1. ?We are five friends and do not know what to save for. Help us choose a purpose.?
2. ?We prefer an emergency reserve, and each of us can comfortably contribute USD 10 per month.?
3. ?Compare a one-time USD 600 goal with a repeating annual cycle.?
4. ?Give us objectives and a month-by-month roadmap, with your assumptions.?
5. ?Explain shares, fines and voting in simple terms. Which choices do we still need to make??

Also try ?How do I join a group??, ?What does created payment status mean??, ?Why do I owe catch-up contributions?? and ?How does the treasurer contribute without paying themselves?? The helper receives `SAVEKIN_HELP.md` as product knowledge and distinguishes current features from future work.

After the initial API key/model configuration, messages require data-sharing consent. Each request includes the message, the last 12 saved messages, and limited selected-group context. General planning includes no account/group records. References, evidence notes/files, names, emails, invitation codes and other members' individual records are excluded from automatic context. Anything typed in chat is sent, so avoid passwords and sensitive details. Chats are private to the signed-in SaveKin account and stored in the local database. Delete chat removes its local transcript; it is not a guarantee of deletion from provider retention systems.

Plans are drafts. The helper can explain, compare choices, suggest goals and practical milestones, and help reason through hypothetical contributions. It cannot execute a decision, create a group, alter rules/shares, vote, approve a request, transfer money, verify a balance, or guarantee returns. Group changes still follow member votes and officer approvals.

No key/model was provided for a real provider test, so AI quality and planning usefulness remain unverified until you enable it. Consent, history limits, ownership, group isolation, non-mutation and unavailable-provider behavior are tested using simulated responses. Web/mobile syntax, the Android export and generated-text escaping are checked. Browser/native visual automation remained unavailable in this session.

## Review the collapsible sidebar

The first screenshot's full labeled sidebar remains the desktop layout. **Collapse menu** hides the whole sidebar and expands the content. On narrower screens **Menu** opens the full labeled navigation as a drawer, rather than replacing words with a row of icons. Close it with Close menu, the background overlay or Escape. It includes Overview, Join a circle, How it works and SaveKin helper. Keyboard focus remains within the drawer while open on small screens.

Restart the backend and use Ctrl+F5 after updating, because the new helper JavaScript and API routes need the updated server.

## Elastic alternative

The helper now supports Elastic Agent Builder managed models as an alternative to OpenAI. No OpenAI key is required for that path. Follow [ELASTIC_SETUP.md](ELASTIC_SETUP.md) to create the cloud project, provision the dedicated agent and use the runtime key locally. Integration and error paths are mock-tested; actual account access and model generation remain unverified. Elastic may retain provider-side conversations; the OpenAI-specific `store:false` statement does not apply to Elastic. The agent receives the product guide as context; this version does not create a searchable Elasticsearch document index.


## Group navigation and chat update

New members start by creating or joining a circle (or asking the helper to plan). Returning accounts restore their last selected circle from the server, including when switching between web and mobile. Overview contains contributions, shares, arrears, the recorded pool and the main actions. Menu contains group pages and create/join/switch options. Decision summaries show people and amounts instead of JSON identifiers.

Open the bottom-right chat shortcut from any signed-in screen. AI data-sharing consent is remembered per account, provider and notice version; revoke it within chat. On web, Enter sends and Shift+Enter starts a new line. Android keeps a multiline composer and an explicit Send message button. Chat history remains private to the signed-in account.

Sandbox checkout updates its estimated fee and total automatically as the amount changes. Payment buttons are removed while a replacement quote loads. Only confirmed net savings are credited.

Restart the backend with your usual sandbox launcher and `--with-elastic`, then refresh the browser and reload Expo to use this update. Existing server credentials are never copied to source files.


## Current review: account and group screens

The latest helper replaces the earlier popup: both entry points open a dedicated screen. Click the sidebar name/avatar for Profile; Overview/Menu restores your group without discarding an unsent chat draft. Test a profile name/photo change, then check Members in another account. Profile email changes require a verification code; recovery and verification require SMTP or explicit local mail previews (see README).

Menu now includes Discussions, Group treasury, Notifications, Profile and the helper. Two signed-in current members can exchange text messages; notification polling refreshes every 15 seconds. Discussions are not official votes. Former members cannot fetch messages. A voted treasurer replacement begins a paused handover: nominee account declaration, outgoing statement, member approval of terms/fees, external transfer declaration, and separate receipt/president confirmations. The ledger pool must match available group funds. This is a manual record, not an automatic transfer or PayPal account onboarding. Sandbox activation waits for matching server credentials. Do not replace the old credentials until old pending payments and payouts have been reconciled.

Restart with the existing launcher and `--with-elastic`, refresh the web page (Ctrl+F5), then reload Expo. `expo-image-picker` is included for mobile profile pictures. No user credentials or real transfer are needed for automated tests.


To review email flows without an email service, launch with `--restart-local --with-elastic --local-mail`. Request a code in the app, then open the newest `.eml` file in `data/mail-preview/` locally. This is explicitly a development preview; no email is sent. Leave off `--local-mail` and configure SMTP for actual email delivery. Keep codes private.
