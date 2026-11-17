# Manual UI/UX regression checklist

Use disposable learner accounts and published sample questions. Do not use live
timed attempts to test expiry, failures or submission.

- [ ] Guest and signed-in navigation: desktop and mobile menu, account/library
  disclosures, Escape, focus return, skip link and existing category → exam → module routes.
- [ ] Light, dark, sepia and System: all public pages, Profile, Learning Space,
  setup, questions, feedback and results; change device appearance while System
  is selected. Profile and header selectors stay synchronized after refresh.
- [ ] Disable JavaScript, then block browser storage: links/forms remain usable;
  no-JS themes follow the device. Storage failure explains page-only preference.
- [ ] Learning Space: empty and populated states, older unfinished sessions,
  completed/expired mocks, Practice progress and Revision Bank counts. Another
  account's activity, notes and answers never appear.
- [ ] Keyboard only: Tab/Shift+Tab order, visible and unobscured focus, radio arrow
  keys/Space, select menus, disclosures, bookmark toggles and password visibility.
- [ ] Screen reader (NVDA/VoiceOver): headings, language changes, field errors,
  bookmark/theme/save status, answer locking and palette labels; no repeated
  countdown announcements every second.
- [ ] 320/360px phone, tablet and desktop; actual browser zoom at 200% and larger
  text. No horizontal page scrolling or clipped English/Bengali options. Timer,
  palette, Previous, Save & Next and Submit remain reachable on short viewports.
- [ ] Mock attempt: select/change/clear, mark review, section jump, save retry,
  refresh/resume, final confirmation and results. No solution/correctness markup
  before finalization; saved answers and original deadlines survive navigation.
- [ ] Practice, previous-year practice and Revision: reveal only at the existing
  boundary, locked choices, explanation disclosures, navigation, bookmarks,
  personal notes and historical review. Previous-year practice still resets on reload.
- [ ] Reduced motion and forced-colors mode; inspect contrast on text, controls,
  selected/correct/incorrect states. Icons/labels convey status without color.
- [ ] Empty filters, invalid forms, unavailable content and 403/404/500 states:
  clear recovery links, no internal exception details, no misleading save claims.
- [ ] Cold/warm load on a throttled connection: no missing/CDN assets, disruptive
  jumps or duplicate event handlers. Verify production cache/compression headers
  and representative dashboard query timings separately from local test results.

Automated Edge tests use a 640×400 CSS-pixel viewport for the reflow equivalent
of a 1280×800 desktop at 200% zoom. This does not replace the manual browser-zoom
and assistive-technology checks above.
