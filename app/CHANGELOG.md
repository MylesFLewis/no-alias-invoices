# Changelog

## v0.27 — 14 October 2026

- Added detailed SMTP diagnostics to the Docker log for invoice email failures, including the SMTP exception type, provider response code and provider response text where available.
- Log SMTP connection, authentication and successful server acceptance stages without logging the SMTP password.
- Preserve the existing safe user-facing delivery status and retry behaviour while making authentication, TLS and provider rejection failures diagnosable from the container log.

## v0.26 — 14 October 2026

- Add an optional Email invoice to contact checkbox, recipient display and server-side validation against the selected saved contact.
- Deliver the final saved PDF through certificate-verified STARTTLS/SSL SMTP, with a durable queue and delivery status in History.
- Preserve invoices on mail failure, prevent duplicate save requests from sending twice, and require confirmation for manual retries after failed or uncertain delivery.
- Block test removal/number reuse for sent, sending or uncertain invoices; keep contact numbering, downloads and folder copies.
- Add optional SMTP fields to the Unraid template and configuration guidance in Settings.

## v0.25 — 6 October 2026

- Added an Assigned contact dropdown to the venue form, populated with existing contacts.
- Allowed assigning, moving or releasing venues directly from Venues; Available to all contacts makes a venue shared.
- Automatically enabled Contact has assigned venues when assigning a venue, and refreshed invoice dropdowns after saving.

## v0.24 — 6 October 2026

- Added Delete buttons for saved contacts and venues, requiring two confirmation prompts.
- Deleting a contact releases its assigned venues for all contacts; deleting a venue removes it from future selections.
- Preserved saved invoice details, PDFs and numbering references when deleting saved details.

## v0.23 — 5 October 2026

- Added an optional Other details field to each invoice service and a PDF column before Fee.
- Fixed service-table widths to the page margins and enabled text wrapping and expanding row heights.
- Allowed very tall service rows to continue across pages with repeated headers; retained compatibility with older templates.

## v0.22 — 5 October 2026

- Added CSV batch venue import with a downloadable template and preview before saving.
- Matched Company name to existing contacts and enabled assigned venues automatically; blank company names create shared venues.
- Updated matching venues without duplicates and blocked conflicting assignments, invalid rows and stale previews.

## v0.21 — 5 October 2026

- Added per-contact payment terms in days and automatically calculate invoice due dates from the invoice date.
- Added the due date to generated invoices while retaining compatibility with existing templates.

## v0.20 — 5 October 2026

- Added per-contact invoice numbering with optional prefixes and independent next-number counters.
- Contacts can use their own numbering sequence or continue using the main invoice counter.

## v0.19 — 5 October 2026

- Added optional contact-to-venue assignment and filter invoice venue choices to the selected contact.
- Venues not assigned to a contact remain available to all contacts.

## v0.18 — 5 October 2026

- Split Saved Details into separate Contacts and Venues tabs.
- Added contact email addresses and improved dynamic contact/address formatting on generated invoices.

## v0.17 — 5 October 2026

- Added optional Work Order Number to invoice service rows and generated PDFs.

## v0.16 — 5 October 2026

- Generate service rows dynamically so invoices only contain rows for entered services.
- Sort generated invoice services by date worked.

## v0.15 — 5 October 2026

- Added a user-selectable Invoice Date to invoice creation.

## v0.14 — 5 October 2026

- Increased the company logo upload limit and normalised invoice logo sizing.

## v0.13 — 5 October 2026

- Added configurable business name and company logo support.

## v0.12 — 5 October 2026

- Added a Settings page for invoice numbering and business details.

## v0.11 — 5 October 2026

- Added invoice copies to a configurable persistent output directory.
- Generated filenames use the invoice number followed by ` Invoice`.

## v0.10 — 5 October 2026

- Added dynamic service rows to generated invoices.

## v0.9 — 5 October 2026

- Added selectable invoice dates.

## v0.8 — 5 October 2026

- Improved generated invoice formatting and dynamic contact details.

## v0.7 — 5 October 2026

- Increased logo upload size and improved consistent PDF logo dimensions.

## v0.6 — 5 October 2026

- Added Unraid installation/configuration guidance to the template overview.

## v0.5 — 5 October 2026

- Added configurable invoice output storage.

## v0.4 — 5 October 2026

- Added Docker/Unraid configuration and persistent application data.

## v0.3 — 5 October 2026

- Added application branding and icon support.

## v0.2 — 5 October 2026

- Added saved invoice details and configurable invoice numbering.

## v0.1 — 5 October 2026

- Initial No Alias invoice application.
