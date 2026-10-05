# Changelog

## v0.13 — 5 October 2026

- Collapsed blank business detail lines and omitted blank payment terms in new PDFs.
- Removed empty bank detail rows and hid the Payment Details table when all bank fields are blank.
- Kept the service table clear of the logo as the header shrinks; existing saved PDFs remain unchanged.

## v0.12 — 5 October 2026

- Displayed the selected contact address below Invoice to in new draft and saved PDFs when an address is present.
- Kept Invoice to name-only when the contact address is blank and preserved multiline addresses.
- Saved an address snapshot with each new invoice; existing saved PDFs remain unchanged.

## v0.11 — 5 October 2026

- Split Saved details into separate Venues and Contacts tabs with dedicated save and edit forms.
- Kept Invoice to options connected to Contacts and service Venue options connected to Venues.
- Preserved existing saved recipients, venues and addresses without a data migration.

## v0.10 — 5 October 2026

- Made the service table match the number of services entered, with no unused blank service rows.
- Removed the six-service limit and added rows automatically for additional services.
- Repeated table headers on additional pages and retained date ordering, totals and template styling.

## v0.9 — 5 October 2026

- Sorted services in draft and newly saved invoice PDFs by Date worked, earliest first.
- Kept services on the same date in their entered order.
- Kept invoice date, amounts and existing saved PDFs unchanged.

## v0.8 — 5 October 2026

- Positioned the company logo at the upper left of the public invoice template, matching the original template placement and size.
- Preserved the logo aspect ratio and kept business details and invoice tables in place.
- Existing private-template logos retain their original placement.

## v0.7 — 5 October 2026

- Increased the company logo file-size limit from 5 MB to 10 MB for local files and HTTP(S) URLs.
- Updated logo validation messages, the README and Unraid Overview instructions to show the new limit.
- Kept the PNG/JPEG format and 20-million-pixel limits.

## v0.6 — 5 October 2026

- Added a Business name container field for the web UI heading and new invoices. Blank falls back to existing settings.
- Added a Company logo container field accepting PNG/JPEG URLs or local container paths for invoice PDFs. Blank keeps the template logo; configured logos replace existing artwork or appear in the header.
- Added logo validation and clear errors for inaccessible or unsupported images.
- Added the supplied No Alias logo as the Unraid container icon. This is a template change; existing containers need their Icon URL updated once.

## v0.5 — 5 October 2026

- Added a Changelog tab in the app with the complete release history.
- Added this CHANGELOG.md to the repository and release ZIP.
- App and repository changelogs use the same release notes.

## v0.4 — 5 October 2026

- Created a public GitHub repository with personal details removed from source and the bundled Word template.
- Added automatic Docker builds from versioned release ZIPs, with startup and PDF generation checks before publishing.
- Published latest and version-specific Docker images to GitHub Container Registry.
- Added an Unraid container template, migration instructions and updates through the Unraid Docker interface.
- Added support for a private Word template stored in appdata, preserving the original logo and layout.
- Kept existing settings, saved contacts, invoice history and numbering when switching to the public image.
- New installations start with blank business details, no saved contacts and invoice number 0001.

## v0.3 — 5 October 2026

- Changed Invoice to and Venue fields to dropdown menus populated from saved details.
- Included the saved venue address in generated invoices.

## v0.2 — 5 October 2026

- Added Remove latest test invoice, requiring confirmation of its four-digit invoice number.
- Removing the latest test invoice resets the counter so that number can be reused.
- Restricted removal to the latest invoice and updated the deletion and counter together.
- Introduced versioned ZIP filenames, starting with no-alias-invoices-v0.2.zip.

## v0.1 — Initial release

- Created a local web app that fills a predefined Word invoice template and generates PDF invoices.
- Added editable invoice dates, service lines, venues, prices, deposits and calculated totals.
- Added draft PDF previews and saving invoices with PDF downloads.
- Saved Invoice to recipients, venues and addresses for reuse.
- Added editable business and payment settings and a configurable next invoice number.
- Automatically incremented invoice numbers when saving invoices and displayed them with leading zeros.
- Added invoice history, saved PDF downloads and full database backups.
- Added Docker deployment for Unraid with persistent appdata.
- Corrected the account number and sort code field mapping in the template.
