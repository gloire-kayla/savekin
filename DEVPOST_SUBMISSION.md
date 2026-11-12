# 🏆 SaveKin — Devpost Submission Package

## 📌 Project Overview
- **Project Title:** SaveKin
- **Tagline:** Community-governed savings circles (*Ikimina*) powered by PayPal Checkout & Payouts with an AI Financial Planning Assistant.
- **GitHub Repository:** [https://github.com/gloire-kayla/savekin.git](https://github.com/gloire-kayla/savekin.git) (Open Source MIT License)
- **Primary Category:** PayPal AI Hackathon — Best Financial Inclusion / Best Use of PayPal & AI

---

## 💡 Inspiration
Across the developing world, more than one billion unbanked and underbanked individuals pool funds using community-based rotating savings and credit associations (ROSCAs)—such as **Ikimina** in Rwanda, **Tandas** in Latin America, **Chit Funds** in India, and **Susus** in West Africa. 

While these circles build immense social capital, they suffer from critical vulnerabilities:
1. **Physical Cash Risk:** Keeping cash in locked boxes invites theft or loss.
2. **Bookkeeping Discrepancies:** Paper ledgers or informal WhatsApp records lead to disputes over catch-up arrears, shares, and payouts.
3. **No Financial Advisory:** Members lack accessible tools to model long-term savings goals or understand cycle settlements.

We built **SaveKin** to preserve the community solidarity and peer accountability of *Ikimina* while securing it on **PayPal's global financial rails** and elevating member financial literacy with an **AI Financial Planning Assistant**.

---

## 🚀 What It Does

SaveKin is a full-stack, mobile and web platform that enables trusted groups to organize, fund, govern, and distribute savings cycles transparently:

1. **Share-Based Contributions & Exact Fee Engine:**
   - Members contribute flexibly through customizable share units rather than rigid quotas.
   - Built-in real-time fee calculator determines exact PayPal processing fees up-front, guaranteeing that target savings are credited down to the penny.
2. **PayPal Sandbox Checkout & Instant Capture:**
   - Members pay securely via PayPal Orders v2 API with idempotent capture, automatic catch-up arrears resolution, and immediate ledger crediting.
3. **SaveKin AI Financial Planning Assistant:**
   - Powered by **Elastic Cloud Agent Builder** and **OpenAI**, the assistant serves as an interactive financial coach.
   - Members can model hypothetical savings scenarios, understand cycle rules, calculate arrear requirements, and explore multi-month milestones.
   - Designed with strict safety boundaries: AI requires explicit user consent, receives bounded anonymized context, and can never mutate funds or alter votes.
4. **Democratic Multi-Officer Governance:**
   - All critical actions—electing treasurers, adopting rules, assessing fines, or processing early exits—require an enforceable **two-thirds majority vote**.
   - Strict separation of duties: Treasury funds are safeguarded in the treasurer's verified account, but cycle settlements require dual approval from both President and Treasurer.
5. **Automated PayPal Payouts Batch Distribution:**
   - At the conclusion of a savings cycle, the platform executes automated distributions via the **PayPal Payouts REST API**.
   - Batches are submitted idempotently with real-time per-recipient tracking (`SUCCESS`, `PENDING`, `UNCLAIMED`).
6. **Cross-Platform React Native Mobile & Web:**
   - Complete feature parity between modern desktop web and React Native / Expo mobile app, featuring persistent session management and live discussions.

---

## 🛠️ How We Built It

- **Backend Architecture:** Pure Python 3.11+ threading HTTP server with zero external framework overhead, ensuring fast startup, auditability, and minimal footprint.
- **Database & Ledger:** SQLite3 with strict foreign key constraints, ACID transaction isolation, and double-entry ledger bookkeeping.
- **PayPal Integration:**
  - **Orders API v2:** Real-time quote generation, intent capture, and fee reconciliation.
  - **Payouts API v1:** Batch payout distribution, idempotent retry keys, and status polling.
  - **Webhooks Listener:** Cryptographic signature verification for asynchronous payment captures and payout lifecycle events.
- **AI Stack:**
  - **Elastic Cloud Agent Builder:** Managed custom agent with domain-specific knowledge embeddings (`SAVEKIN_HELP.md`).
  - **OpenAI API:** GPT-4o-mini engine with strictly bounded conversational history and zero data persistence flags (`store: false`).
- **Frontend & Mobile:**
  - **Web:** Vanilla JavaScript ES6+ / HTML5 with reactive DOM components and collapsible responsive layout.
  - **Mobile:** React Native with Expo SDK, custom tab navigation, and cross-platform secure storage.
- **Testing & Quality Assurance:** Comprehensive automated Python test suite containing **112 test cases** covering edge cases: duplicate captures, interrupted payouts, network timeouts, multi-officer votes, and AI boundary safety.

---

## 🏔️ Challenges We Ran Into

- **Cent-Precision Currency Math:** In community circles, fractional cents in PayPal percentage fees can cause arithmetic drift. We implemented a strict integer-cent decimal engine that prevents rounding leaks across share multipliers.
- **PayPal Payouts Batch Asynchrony:** In sandbox environments, payouts transition through `PENDING` before reaching `SUCCESS`. We engineered idempotent batch tracking (`PayPal-Request-Id`) that prevents accidental double-payouts even if a network timeout occurs during distribution.
- **AI Safety & Privacy Constraints:** We refused to let the AI assistant have unrestricted access to private financial data or execution capabilities. We created an explicit consent boundary where the helper can explain records and guide decisions, but cannot approve transactions or initiate transfers.

---

## 🎉 Accomplishments That We're Proud Of

- **100% Pass Rate on 112 Unit Tests:** Robust coverage validating payment integrity, voter quorum, handover workflows, and AI safety boundaries.
- **Frictionless 60-Second Judge Testing:** Built a 1-click sample seed endpoint (`POST /api/demo/seed`) that populates the complete "Kigali Community Circle" with members, shares, and a ready-to-distribute cycle in under 1 second.
- **Full Web & Mobile Parity:** Seamless experience across both desktop browsers and React Native mobile devices with persistent sessions.

---

## 📚 What We Learned

- The architectural elegance of combining PayPal's high-trust payment APIs with decentralized community voting.
- How to structure idempotent financial workflows where transient network failures or interrupted browser callbacks never cause funds to disappear or duplicate.
- How to design responsible AI agents in fintech that augment user financial literacy while strictly respecting data boundaries and human consensus.

---

## 🔮 What's Next for SaveKin

1. **PayPal Commerce Platform Integration:** Onboard multiple community treasurers dynamically through PayPal Partner multi-tenant OAuth.
2. **WhatsApp & SMS Bot:** Allow low-connectivity rural members to check their share balances and receive payout alerts via WhatsApp Business API.
3. **Multi-Currency Support:** Integrate automatic real-time FX conversion between USD, Rwandan Francs (RWF), Kenyan Shillings (KES), and Nigerian Naira (NGN).
4. **Group Micro-Lending:** Enable circular lending within the group where interest earned is democratically redistributed to all share-holders at cycle settlement.

---

## 🧭 60-Second Quick Demo for Judges

1. **Launch SaveKin:**
   ```powershell
   .\start.ps1
   ```
   Open `http://127.0.0.1:8000` in your browser.
2. **Load Sample Circle:**
   Click the **"✨ Load Sample Circle"** button. This automatically provisions the *"Kigali Community Circle"* with President Alice, Treasurer Bob, and Member Charlie.
3. **Ask the AI Assistant:**
   Click the **SaveKin Helper** bubble in the bottom right corner and ask: *"How do our share allocations and catch-up arrears work?"*
4. **Test Settlement & PayPal Payouts:**
   Click **Settlement**, view the approved payouts table, and click **"Send approved payouts"** to observe live batch distribution and status tracking.
5. **Run the Full Test Suite:**
   ```powershell
   py -m unittest discover -s tests -v
   ```
   All **112 unit tests** will execute and pass cleanly in ~70 seconds!
