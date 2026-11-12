# 🎬 SaveKin — Official 3-Minute Demo Video Script (< 180s)
> **Target Duration:** 2 minutes 45 seconds (Buffer of 15 seconds to stay strictly under the 3-minute Devpost limit).  
> **Resolution:** 1080p (1920x1080) or 4K.  
> **Tool for Recording:** OBS Studio, Loom, or Screen Studio.

---

## ⏱️ Timeline Summary

| Time | Scene | Focus |
|---|---|---|
| **0:00 - 0:25** (25s) | **Introduction & Problem** | Traditional *Ikimina* / ROSCA savings circles, cash risks, and lack of ledger transparency. |
| **0:25 - 0:55** (30s) | **SaveKin Overview & AI Assistant** | 1-Click Circle Seed, transparent dashboard, and SaveKin AI Financial Planning Assistant. |
| **0:55 - 1:35** (40s) | **PayPal Contribution & Fee Transparency** | Transparent share-based contributions with real-time PayPal fee calculation and checkout. |
| **1:35 - 2:05** (30s) | **Democratic Governance & Ledger** | 2/3 majority voting on officer appointments, rules, and dual-entry ledger visibility. |
| **2:05 - 2:35** (30s) | **Settlement & PayPal Payouts** | Dual-officer settlement approval, idempotent PayPal Payouts batch distribution, per-member status. |
| **2:35 - 2:50** (15s) | **Conclusion & Vision** | Bridging traditional community trust with modern PayPal rails and responsible AI. |

---

## 🎙️ Step-by-Step Script & Actions

### Scene 1: Introduction & The Problem (0:00 – 0:25)
- **Visual:** Open with the SaveKin landing page or a split visual of traditional rotating savings (*Ikimina* / ROSCA) and the SaveKin login screen.
- **Voiceover:**
  > *"Across the world, over a billion people rely on informal community savings circles—known as Ikimina in Rwanda, Chit Funds in India, or Tandas in Latin America. While built on strong community trust, they suffer from three major vulnerabilities: the physical risk of holding cash, fragmented paper ledgers, and zero financial advisory tools.*
  > *Meet **SaveKin**—an intelligent, community-governed savings circle platform powered by PayPal and responsible AI."*

---

### Scene 2: SaveKin Dashboard & AI Financial Assistant (0:25 – 0:55)
- **Action On Screen:**
  1. Click **"✨ Load Sample Circle"** to instantly load the *"Kigali Community Circle"*.
  2. Show the circle overview: 3 members (Alice as President, Bob as Treasurer, Charlie as Member), 5 shares, and current pool.
  3. Click the **"SaveKin Helper"** chat bubble in the bottom right corner.
  4. Type or select: *"Explain how our share contributions and catch-up arrears work."*
- **Visual:** The AI instantly responds with context-aware, respectful financial explanations derived from the group's agreed rules and `SAVEKIN_HELP.md`.
- **Voiceover:**
  > *"With SaveKin, onboarding is instant. Here we have our Kigali Community Circle. Members save in flexible 'shares' rather than rigid fixed amounts.*
  > *Our embedded **SaveKin AI Assistant**—integrated with Elastic Cloud Agent Builder and OpenAI—acts as an on-demand financial literacy coach. With explicit member consent, it explains rules, arrears, and budget milestones without ever having authorization to move funds or alter governance."*

---

### Scene 3: PayPal Contributions & Transparent Fee Engine (0:55 – 1:35)
- **Action On Screen:**
  1. Switch to member Charlie's perspective.
  2. Navigate to **Contributions** / **Pay with PayPal Sandbox**.
  3. Enter an amount (e.g., `$20.00`) and click **Calculate total**.
  4. Highlight the transparent fee quote (Target Savings vs. Provider Fee vs. Gross Total).
  5. Click **Pay with PayPal Sandbox**; show the checkout window and instant capture.
  6. Return to overview; show the pool balance increase and ledger update in real time.
- **Voiceover:**
  > *"When members contribute, SaveKin integrates directly with PayPal Checkout.*
  > *Unlike apps that hide fees, our transparent fee engine calculates the exact PayPal percentage and fixed fee upfront, guaranteeing that the member's target savings are credited down to the penny. The shared ledger updates immediately for every member, eliminating disputes and manual reconciliation."*

---

### Scene 4: Democratic Governance & Dual-Officer Ledger (1:35 – 2:05)
- **Action On Screen:**
  1. Click **Rules** & **Decisions**.
  2. Show the rule requiring a **2/3 majority vote** for all governance changes (fines, officer appointments, exit terms).
  3. Show the **Discussions** feed where members coordinate.
  4. Highlight the **Double-Entry Ledger**: every single contribution, fee, and adjustment is permanently audited.
- **Voiceover:**
  > *"Governance in SaveKin is truly democratic. Crucial decisions—such as electing officers or amending group fines—require an enforceable two-thirds majority consensus.*
  > *Furthermore, SaveKin enforces multi-officer separation of duties: funds are held in the group treasurer's verified PayPal account, but treasury contributions and cycle settlements require independent review and approval by the President."*

---

### Scene 5: Cycle Settlement & PayPal Payouts Batch Distribution (2:05 – 2:35)
- **Action On Screen:**
  1. Navigate to **Settlement**.
  2. Show the cycle reaching completion with verified member payouts.
  3. Sign in as Bob (Treasurer) and click **"Send approved sandbox payouts"**.
  4. Show the PayPal Payouts batch submission using PayPal's REST Payouts API.
  5. Show the real-time status of each member's payout (Batch ID, Item Status: `SUCCESS`, claimed amount).
- **Voiceover:**
  > *"When the savings cycle ends, SaveKin automates distribution through the **PayPal Payouts REST API**.*
  > *Both the President and Treasurer approve the audited settlement table. With one click, the Treasurer dispatches an idempotent batch payout directly into each member's PayPal account. Live payout statuses are displayed per-member, guaranteeing complete transparency from contribution to payout."*

---

### Scene 6: Mobile Experience & Conclusion (2:35 – 2:50)
- **Action On Screen:**
  1. Quick cut to the **React Native mobile app** running on an Android phone/simulator.
  2. Show the same Kigali Community Circle with matching pool totals and live notification badges.
  3. End on the SaveKin title card with GitHub repository link: `https://github.com/gloire-kayla/savekin`.
- **Voiceover:**
  > *"With full feature parity on React Native mobile, SaveKin brings community savings circles into the modern era—blending traditional solidarity with the global reach of PayPal and responsible AI.*
  > *Thank you!"*

---

## 💡 Quick Tips for the Presenter:
1. **Pacing:** Speak clearly and at a confident, natural pace.
2. **Audio:** Use a clean microphone with noise cancellation.
3. **Cursor:** Enable mouse-click highlighting or zoom in slightly when clicking buttons.
4. **Time Check:** If you run long on the intro, trim 5 seconds from the governance section to ensure the video stays safely below 2:50.
