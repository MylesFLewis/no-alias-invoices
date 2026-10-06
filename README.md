# Invoice app repository

Build versioned Docker images for a local invoice app and update them through Unraid. Public releases contain blank settings, no saved contacts and a sanitized Word template. Your personal data belongs in the private `/data` volume.

## First GitHub setup

This public repository is ready to use. The v0.4 image has passed startup and PDF generation tests. Do not upload earlier private release ZIPs.

The workflow extracts the highest numeric release in `releases`, builds it, checks startup and PDF conversion, then publishes `ghcr.io/mylesflewis/no-alias-invoices:latest` and a version tag. The release ZIP contains the complete sanitized app source and is the build input.

The container image is public and can be pulled without authentication. No Docker Hub account or personal access token is needed for the build.

Download the `unraid-template` artifact from the successful Actions run. It contains an XML template with your exact image address.

## Keep your original layout privately

Before switching your existing installation, copy your original template from your current v0.3 source folder into appdata:

```bash
cp /mnt/user/appdata/no-alias-invoices-app/templates/invoice.docx /mnt/user/appdata/no-alias-invoices/invoice-template.docx
```

Adjust the source path if you extracted the old app somewhere else. Do this before replacing that source folder with the public package. Do not upload `invoice-template.docx` to GitHub. The app prefers `/data/invoice-template.docx`, retaining your original logo and layout. If it is absent, it uses the clean public template.

The app opens the same `invoices.sqlite3`. Existing settings, invoice numbering, contacts and PDFs are retained. New installations start with blank details and invoice number 0001; existing installations retain their current counter.

## Install the Unraid template once

1. Download a full database backup from the existing app's History tab.
2. Copy the generated XML to `/boot/config/plugins/dockerMan/templates-user/my-no-alias-invoices.xml` on Unraid.
3. Stop the existing `no-alias-invoices` container and remove the container in Unraid. Keep its appdata directory.
4. In the Docker tab choose **Add Container**, select the `no-alias-invoices` user template, verify port 8085 and appdata `/mnt/user/appdata/no-alias-invoices`, then Apply.
5. Open the WebUI and check settings, saved contacts, invoice history and a draft PDF.

The bundled XML in `unraid/my-no-alias-invoices.xml` is already configured for this repository and can also be used directly.

## Later updates

Upload a sanitized `no-alias-invoices-v0.5.zip` (or later) into the repository's `releases` folder using **Add file → Upload files**, and commit it to `main`. Each ZIP contains a top-level `no-alias-invoices` folder and a VERSION file matching its filename. Keep only public-safe source in release ZIPs; do not include a database or private template.

Wait for **Build invoice image** in Actions to succeed. Then in Unraid's Docker tab select **Check for Updates**, and update this container. Always use `:latest` for this flow. A specific `:v0.4` tag stays on that version.

A failed build leaves the published `latest` image in place. To roll back, edit the container's Repository field to a previous version tag and Apply. Appdata stays on the server.

## Local operation

The web app has no login. Keep it on your trusted LAN or WireGuard VPN. No public router port or reverse proxy is required. The interface uses no external assets. PDF conversion runs in the container.

Source: [GitHub container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for all releases. The same history is available in the app under **Changelog**. Include updated release notes in each future version.

## Company branding (v0.6)

The Unraid template includes **Business name** (`BUSINESS_NAME`) and **Company logo** (`COMPANY_LOGO`). Business name sets the web UI heading and the business line on new invoices; blank falls back to the app's saved business name.

Company logo accepts a PNG/JPEG HTTP(S) URL or a file path **inside the container**. For example, place `logo.png` in `/mnt/user/appdata/no-alias-invoices/` on Unraid and enter `/data/logo.png`. `file:///data/logo.png` also works. Images must be at most 10 MB and 20 million pixels. Leave blank to keep the logo already in your private Word template. A configured logo replaces template artwork while retaining its position, or is placed at the upper left of the public template at the original template size (v0.8 onward). Existing saved PDFs stay unchanged.

For an existing installation, update the container image to v0.6, then **Edit → Add another Path, Port, Variable, Label or Device → Variable** to add `BUSINESS_NAME` and `COMPANY_LOGO` (these fields are automatic on new installations using the updated XML). Apply the changes and refresh the app. The Docker Icon URL is separate from the invoice logo.

## Saved contacts and venues (v0.11)

Use **Contacts** to save and edit Invoice to recipients and their addresses. Use **Venues** to save and edit venues and their addresses. The New invoice dropdowns use these saved entries. Existing saved details appear in their respective tabs automatically after updating.

## Per-contact invoice numbering (v0.15)

In **Contacts**, enable **Use separate invoice numbering for this contact**, enter a prefix and the next invoice number, then save the contact. For example, `LEA` and `169` produce `LEA0169`; use `LEA-` for `LEA-0169`. The number is padded to at least four digits. Each enabled contact needs its own prefix.

The New invoice screen shows the next number for the selected contact. Saving advances only that contact's counter. Previews do not use a number. Leave the checkbox unticked to use the main number in Settings. Disabling separate numbering retains the contact's prefix and counter for later use. Existing invoices and PDFs retain their original numbers.

The latest test invoice can still be removed from History, resetting the counter used by that invoice. If its counter or prefix has since been changed manually, automatic removal/reset is blocked to avoid overwriting those changes.

## Assigned venues (v0.17)

In **Contacts**, tick **Contact has assigned venues**, select saved venues and save the contact. Each venue can be assigned to one contact; venues reserved for another contact are shown but cannot be selected.

The invoice Venue dropdown shows the selected contact’s assigned venues plus all unassigned venues. Other contacts cannot select its assigned venues. Switching Invoice to refreshes every service dropdown and clears selections that are no longer available.

To release a venue, untick it in the contact’s selection list and save. Unticking **Contact has assigned venues** and saving releases all of that contact’s venues. Unassigned venues are available to all contacts. Existing invoices and their PDFs are preserved.

## Invoice PDF folder (v0.18)

Completed invoices are copied to a writable folder, named **LEA0169 Invoice.pdf** (or **0169 Invoice.pdf** for main numbering). Device downloads and History remain available. Draft previews are not copied. Older invoices are not exported automatically.

New installations have an **Invoice PDF folder** path in the Docker template. Choose your Unraid folder; its container path is `/data/invoices`, with Read/Write access. The default is `/mnt/user/appdata/no-alias-invoices/invoices`.

For an existing installation, update the image, then choose **Edit → Add another Path, Port, Variable, Label or Device → Path**. Set Name to **Invoice PDF folder**, Container Path to `/data/invoices`, Host Path to your desired folder and Access Mode to **Read/Write**, then Apply. Without that extra mapping, copies go into an `invoices` subfolder in your existing Appdata directory.

If the copy fails, the invoice stays saved in History and the app reports the copy error. A different existing file with the same filename is preserved. Removing the latest test invoice also removes its folder copy when it still matches the saved PDF.

## Contact payment terms (v0.20)

Set **Payment term days** in Contacts to calculate an invoice due date using calendar days from **Invoice date**, not Date worked. For example, 5 October 2026 plus 30 days is due on 4 November 2026. Zero means due on the invoice date. Blank keeps the general payment terms in Settings and does not add a calculated due date.

When a contact has payment days, its payment timing replaces the general payment-term wording on new PDFs. The contact term and calculated due date are stored with each saved invoice; changing a contact later does not change existing invoices. Whole numbers from 0 to 3650 are supported.

## Work order numbers (v0.21)

Each service has an optional free-text **Work order number**. New PDFs show it in a column immediately after **Date Worked**, with blank cells for services where it is omitted. Existing four-column templates are adapted automatically during generation; the stored Word template is not overwritten. Previously saved PDFs stay unchanged.

### Import venues from CSV

In **Venues**, download the CSV template, fill it in, choose the file and select **Preview import**. Check the preview, then select **Import venues**.

The headings are `Venue name,Address,Company name`. Company name must match an existing contact (matching ignores case); leave it blank for a venue available to all contacts. Addresses containing commas or line breaks must be quoted, as spreadsheet CSV exports do automatically. Save as UTF-8 CSV, with at most 1 MB and 1,000 venues.

Matching venue names update existing entries rather than creating duplicates. Importing an assigned venue enables **Contact has assigned venues** for that contact. A venue already assigned to another contact must be released before importing a different assignment. All row errors must be fixed before the batch can be imported.

Each invoice service has an optional **Other details** text field (up to 1,000 characters), shown in its own PDF column before Fee. Long text wraps within fixed columns; rows grow or continue onto another page with repeated headers.

Contacts and venues can be deleted using their **Delete** button. Both confirmation prompts must be accepted. Saved invoices and PDFs are retained. Deleting a contact releases its assigned venues so all contacts can select them.
