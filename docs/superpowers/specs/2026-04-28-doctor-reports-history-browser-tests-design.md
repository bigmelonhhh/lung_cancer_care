# Doctor Reports History Browser Tests Design

## Context

The current frontend tests for the Django server-rendered pages mostly verify backend views, template output, context values, and static asset references. They do not execute the JavaScript layer in a real browser, so interactions implemented with Alpine, HTMX, fetch, and DOM events can regress without being caught.

The first browser automation scope is the doctor-side reports history image archive workflow. This area already has backend coverage for archive data grouping, filtering, permissions, batch archive behavior, and AI warning handling. The new tests should focus on browser behavior that existing Django tests cannot prove.

## Goal

Add a small, separate Playwright browser test suite for doctor reports history image archive interactions.

The suite should verify:

- HTMX-driven tab/content loading works in a real browser.
- Image preview opens and closes through Alpine-managed state and teleported DOM.
- Date filter frontend validation blocks invalid ranges before a request is sent.
- Archive edit mode can be entered and submits the expected request payload.

## Non-Goals

- Do not replace existing Django `TestCase` coverage.
- Do not introduce visual snapshot testing in the first iteration.
- Do not migrate existing Python tests into the browser suite.
- Do not test backend archive service internals through Playwright; those remain covered by Django tests.
- Do not add broad browser tests for patient-side flows in this first pass.

## Chosen Approach

Use Python Playwright with Django live-server style tests.

This keeps browser tests close to the existing Django data setup model: tests can create users, patients, uploads, and report images through ORM fixtures, then open the page through a live Django test server. It avoids a separate Node-based test data bootstrap layer.

The browser tests must live in a dedicated folder:

```text
tests/browser/
```

The first doctor-side file should be:

```text
tests/browser/web_doctor/test_reports_history_images.py
```

This keeps browser automation visibly separate from the existing app-level Django tests under `web_doctor/tests/` and `web_patient/tests/`.

## Test Entry Point

Add a separate command for browser automation rather than expanding `npm run test:ui`.

Proposed command:

```bash
npm run test:browser
```

The command should run only the dedicated browser test folder, for example:

```bash
python manage.py test tests.browser --keepdb --noinput
```

The suite should fail with a clear message if Playwright is missing or browsers are not installed.

## Test Data

Each browser test should create only the data it needs:

- A doctor user.
- A patient attached to that doctor.
- At least one patient-origin report upload.
- At least one report image with a stable test image URL.
- A checkup library entry when testing checkup archive category selection.

Tests should authenticate through Django test client session state or a helper that transfers login cookies into the Playwright browser context. They should not depend on manual login UI unless the login UI is itself under test.

## Initial Test Cases

### 1. Image Archive Tab Loads

Open the doctor patient workspace reports history page. Click the image archive tab and assert that:

- `#reports-history-content` contains the image archive form.
- At least one image card is visible.
- The content is loaded through the same route used by the production HTMX flow.

### 2. Image Preview Opens And Closes

Click an image card. Assert that:

- The teleported preview overlay becomes visible.
- The preview image `src` matches the clicked image URL.
- Clicking the close button or pressing Escape hides the overlay.

### 3. Invalid Date Range Is Blocked

Set `startDate` later than `endDate`, submit the filter form, and assert that:

- The browser alert text is `开始日期不能晚于结束日期`.
- No HTMX request replaces `#reports-history-content`.

### 4. Archive Edit Submits Expected Payload

Click `编辑归档`, select a category and report date, then click `提交归档`. Assert that:

- The controls become visible in edit mode.
- The POST request targets the batch archive endpoint.
- The JSON payload includes `image_id`, `category`, and `report_date`.

Backend persistence details can remain covered by existing Django tests.

## Selectors

Prefer stable `data-testid` selectors for new browser tests. Add them only where needed and keep them behavior-neutral.

Proposed test IDs:

- `reports-history-content`
- `reports-tab-images`
- `archive-filter-form`
- `archive-date-start`
- `archive-date-end`
- `archive-image-card`
- `archive-edit-button`
- `archive-submit-button`
- `archive-category-select`
- `archive-date-input`
- `image-preview-overlay`
- `image-preview-close`

Existing IDs can still be used when they are already stable, such as `#reports-history-content`.

## Error Handling

The browser test command should make setup problems obvious:

- If Playwright Python package is missing, print the install step.
- If Chromium is missing, print the browser install step.
- If the live server cannot start, fail the test normally with Django output.

## CI And Local Usage

The browser suite should be opt-in at first:

- Local fast checks keep using existing Django tests.
- Browser checks run with `npm run test:browser`.
- CI can add the command after the suite is stable.

This avoids slowing every developer loop while still creating a clear path for interaction coverage.

## Acceptance Criteria

- A dedicated `tests/browser/` folder exists for Playwright automation.
- The first browser test file targets doctor reports history image archive interactions.
- Browser tests are runnable through a separate command.
- Existing Django tests continue to run unchanged.
- The first suite covers at least the image archive tab load and image preview interaction; date validation and archive payload tests can be added in the same implementation pass if setup remains manageable.

