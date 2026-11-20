# UI Naming Contract

## Brief for the design AI

Redesign **Mock Exam Platform**, a competitive-exam preparation app for English
and Bengali readers. The current visual design is not approved. Propose fresh
visual directions; do not treat the existing palette, typography or layouts as
requirements. Focus on the shared shell, navigation, discovery, account and
membership experience. Question/answer screens will be designed separately.

## Stable product names

Use these labels consistently across mockups and component specifications.

| Label | Meaning |
|---|---|
| Home | Public starting point and exam discovery |
| Previous-Year Papers | Published past papers; free and unlimited |
| Mock Tests | Timed tests, separate attempts and results |
| Practice Sets | Untimed question practice |
| Question Library | Navigation group for Exam Authorities and General Questions |
| Exam Authorities | Organizations that conduct exams |
| General Questions | Published general-question collections |
| Learning Space | Personal progress, recent activity and resumable sessions |
| My Revision Bank | Saved questions and revision activity |
| Profile | Account details and reading preferences |
| Plans & pricing | Free/Premium comparison and purchase entry point |
| Plans & billing | Signed-in membership and order-management entry point |
| Free / Premium | Subscription tiers; do not introduce extra tiers |
| Free Demo | The shared, fixed Mock Test designated for an exam |

Keep **exam**, **Mock Test set**, **attempt**, **Practice session** and **question**
distinct. A retake creates another attempt of a set. A question is not a session.

## Shared component names

Name design frames/components: `AppShell`, `Header`, `PrimaryNavigation`,
`AccountMenu`, `MobileNavigation`, `AppearanceSelector`, `Footer`, `Breadcrumbs`,
`ExamCard`, `ModuleCard`, `PlanCard`, `MembershipSummary`, `OrderStatus`,
`UpgradePrompt`, `AuthForm`, `EmptyState`, `ErrorState` and `StatusMessage`.
These are design handoff names, not a request to rename existing source files.

## Membership and account constraints

- Free: one selected exam, its designated Free Demo with unlimited retakes, and
  a configurable lifetime Practice allowance initially set to 50 distinct questions.
- Premium: all supported exams and available Mock/Practice sets. Monthly,
  Quarterly and Yearly plans use Admin-configured INR prices; use placeholders
  rather than inventing prices.
- Make **Get Premium** easy to find; use **Buy Premium** for purchase and
  **Renew Premium** for renewal. Include unavailable-checkout and inactive-plan states.
- Only simulated payments exist today. Label test checkout clearly; never imply
  real payment collection or grant Premium from a visual success state.
- Registration fields: Choose a username, Email address (optional), Create a
  password, Confirm your password. Show empty fields, visible labels and errors.
- Expiry preserves Free allowances, attempts, results, bookmarks and history.

## Requested design handoff

Provide 2–3 visual directions, then a recommended desktop/mobile system covering
Home, module landing pages, Login/Register, Profile/Learning Space, Plans & pricing,
checkout status and subscription confirmation. Include guest, Free and Premium
navigation, loading/empty/error states, and light/dark/sepia variants. Prioritize
readable Bengali typography, accessible contrast, keyboard focus and touch targets.

Implementation remains Django templates with shared components and CSS. Preserve
routes, authentication, CSRF, ownership, entitlement rules and existing learning
workflows. Do not redesign question sections, scoring, timers or Django Admin.
