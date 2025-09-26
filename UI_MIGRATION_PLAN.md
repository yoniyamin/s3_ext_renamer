# S3 Manipulator UI Migration Plan

## Context and Current State
- The web app is a single Flask blueprint living in [`s3bucket_wizard.py`](s3bucket_wizard.py) that renders one monolithic template, [`templates/wizard.html`](templates/wizard.html), mixing HTML, inline CSS, and large JavaScript blocks (>4.5k lines total).
- Static assets are limited to a single stylesheet (`static/style.css`) and a small help modal bundle. There is no module-oriented JS/CSS structure today.
- Session handling and AWS credential storage are implemented directly in `s3bucket_wizard.py` (custom in-memory session store). Client-side flows assume the multi-step wizard that currently drives when credentials are collected and when actions are unlocked.

## Goals Recap
1. Replace the step-based wizard with a landing screen for credentials/bucket selection and a single-page file browser experience.
2. Add a persistent "Connected to <bucket>" affordance that lets the user jump back to the landing view to reconnect or swap buckets without re-entering credentials unnecessarily.
3. Introduce an action radial menu inside the file browser that opens dedicated modals (two-step config/results) for rename extension, verify upload, parse URL, and presigned upload/download links (split modals).
4. Keep presigned-link parsing accessible without providing credentials.
5. Split modal markup/JS into their own template/asset files to avoid massive inline blocks.

## Workstreams & Phasing
The plan below breaks the migration into incremental, testable milestones. Each phase should leave the app runnable, with the legacy wizard kept behind a fallback route until final cut-over.

### Phase 0 – Scaffolding & Safety Nets
1. **Routing guard:** Add a temporary feature flag (e.g., environment variable `USE_NEW_UI`) so new templates can be previewed without removing the current wizard.
2. **Shared layout:** Extract shared `<head>` + base styles into `templates/layouts/base.html` using Jinja blocks. Update the legacy wizard to extend this base so we can reuse assets across both UIs during the transition.
3. **Static build folders:** Introduce `static/css/` and `static/js/` subdirectories and update Flask `url_for('static', ...)` references. Begin with minimal placeholder files so future phases have a structure to plug into.

### Phase 1 – Landing Experience
1. **Template:** Create `templates/landing.html` with:
   - Credential form (copied from wizard step 2) plus Select2 bucket dropdown.
   - Prominent "Parse Presigned URL" shortcut that routes to the parser modal even when no credentials exist.
   - Hooks for error/status messaging using existing Flask `flash` patterns.
2. **Backend:** Introduce `/` → landing route and `/legacy` (or similar) → legacy wizard while flag is on. Ensure credential POST reuses the existing session helper (no regressions to auth logic).
3. **Bucket preload:** Add a `/auth/buckets` JSON endpoint that lists available buckets using the provided credentials immediately after login so the landing screen can populate Select2 before navigating to the browser.

### Phase 2 – File Browser Shell
1. **Template:** Create `templates/file_browser.html` to host the main app chrome. Include:
   - Header bar with "Connected to <bucket>" button (wired to a modal or route that reopens `landing.html`).
   - Container for file list (reuse markup from wizard step 4 but remove stepper scaffolding).
   - Placeholder slots for selection summary, breadcrumbs, and the new radial-menu trigger.
2. **Routing:** Add `/browser` route that requires a valid session + bucket selection, redirecting to landing if missing. Share the same data contract as today’s wizard step once credentials are set.
3. **State hand-off:** When landing form succeeds, store the chosen bucket in the session store and redirect to `/browser`. Update existing helper functions that expect bucket selection later in the wizard so they read from the session instead of wizard step state.

### Phase 3 – Action Infrastructure
1. **Modal templates:** Under `templates/modals/`, create dedicated partials for:
   - `upload_link_modal.html`
   - `download_link_modal.html`
   - `rename_extension_modal.html`
   - `verify_upload_modal.html`
   - `parse_url_modal.html`
   Each template should contain `{% block config %}` and `{% block results %}` sections so shared modal chrome can live in `templates/components/modal_shell.html`.
2. **Modal JavaScript:** Add `static/js/modal-manager.js` to handle opening/closing modal shells and step transitions. Extract action-specific logic into files like `static/js/modals/upload_link.js` etc., migrating code from the inline scripts in `wizard.html`.
3. **Backend endpoints:** Refactor the existing routes (`/generate_presigned_url`, `/rename_extensions`, `/verify_upload`, `/parse_presigned_url`) into `/actions/...` endpoints with consistent JSON payloads. Keep old endpoints available (deprecated) behind the feature flag until the frontend swap is complete.

### Phase 4 – Radial Menu & Selection UX
1. **Component:** Implement `templates/components/radial_menu.html` plus `static/css/radial-menu.css` and `static/js/radial-menu.js`. Menu items should be data-driven so visibility toggles can depend on the current selection type.
2. **Integration:** In `static/js/file-browser.js`, expose selection events and update the radial menu trigger within the `selectionInfo` region (ported from wizard). Ensure keyboard/multi-select behaviour is preserved.
3. **Action dispatch:** Wire radial-menu clicks to modal-manager functions. For options requiring a selection, validate that the selection matches constraints (e.g., upload link only on folders) before opening the modal.

### Phase 5 – Polish & Decommission
1. **Connection management:** Finish the "Connected to <bucket>" interaction (drop-down or modal) that supports:
   - Jumping back to landing to fully re-authenticate.
   - Switching buckets using a new `/auth/change-bucket` route that reuses current credentials.
   - Clearing the session when requested.
2. **Responsive/UI cleanup:** Consolidate shared styles into `static/css/main.css`, migrate remaining inline CSS from `wizard.html`, and verify new templates adapt for smaller screens. Apply ARIA roles and focus management for modals.
3. **Legacy removal:** Once the new UI passes testing, retire the old wizard routes/templates and flip the feature flag default. Update documentation and scripts accordingly.

## Testing Strategy
- **Unit/API tests:** Extend `test_security_endpoints.py` or add new tests to cover `/auth/*` and `/actions/*` responses (especially with/without sessions).
- **Frontend smoke tests:** Add a minimal Cypress/Playwright or Selenium script (optional) to exercise landing → browser flow and modal opening to guard against regressions.
- **Manual checklist:** Authenticate, change bucket, run each modal action (rename, verify upload, upload/download links, parse URL) with both files and folders selected, and confirm radial menu availability rules.

## Outstanding Questions / Clarifications Needed
1. **Bucket selection source:** Should the landing page list buckets immediately after credentials are entered (requiring an API call on submit) or lazily once the file browser loads? The UX differs (waiting spinner vs. immediate redirect).
2. **Stored credentials:** When switching buckets, can we assume the original credentials remain valid for all target buckets, or should we allow editing the AWS region/access keys inline during bucket swap?
3. **Presigned parse shortcut:** On the landing page, should "Parse Presigned URL" open a modal overlay or navigate to a dedicated lightweight page? Clarifying this affects routing and asset loading.
4. **Radial menu interaction:** Is the radial menu expected to float near the cursor/selection (context-menu style) or anchored to a fixed "Actions" button in the selection toolbar? The prompt mentions a button and a radial menu—confirm desired behaviour for desktop vs. mobile.
5. **Upload verification scope:** The current implementation performs checksum/metadata checks sequentially. Do we need to enhance this (e.g., multi-threaded, progress bars) during the UI rewrite, or is a UI-only refactor acceptable for now?
6. **Legacy availability:** Should the legacy wizard remain accessible in production (via hidden URL) after launch for a fallback period, or can it be removed entirely once the new UI ships?

Answering these will help finalise the implementation order and prevent rework during the migration.
