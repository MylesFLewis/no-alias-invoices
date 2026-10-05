# Changelog

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
