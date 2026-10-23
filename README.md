# Invoice app repository

Build versioned Docker images for a local invoice app and update them through Unraid. Public releases contain blank settings, no saved contacts and a sanitized Word template. Your personal data belongs in the private `/data` volume.

## First GitHub setup

This public repository is ready to use. The v0.4 image has passed startup and PDF generation tests. Do not upload earlier private release ZIPs.

The workflow extracts the highest numeric archive in `releases` for its sanitized bundled template, overlays the current reviewed `app/` source when its version is at least as recent, builds it, checks startup and PDF conversion, then publishes `ghcr.io/mylesflewis/no-alias-invoices:latest` and a version tag. Older versions use their release ZIP as the build input; v0.26 onward uses the reviewed text source plus the existing public template.

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

For legacy archive releases, upload a sanitized `no-alias-invoices-v0.5.zip` (or later) into the repository's `releases` folder using **Add file → Upload files**, and commit it to `main`. Each ZIP contains a top-level `no-alias-invoices` folder and a VERSION file matching its filename. Keep only public-safe source in release ZIPs; do not include a database or private template.

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

In **Venues**, select **Edit**, choose an **Assigned contact**, and save. You can move a venue to a different contact or choose **Available to all contacts** to release it. Assigning a venue automatically enables the contact’s assigned-venues option.


## Email invoices to saved contacts (v0.26)

Add an email address in **Contacts**. In **New invoice**, choose that contact and tick **Email invoice to contact**. The displayed address is the recipient. Saving still stores the PDF in History, copies it to the invoice folder and downloads it; it also queues that same final PDF as an attachment. Previews never send mail. The checkbox starts unticked and clears after saving or changing contact. It is disabled if SMTP is not configured or the selected contact has no email.

For an existing Unraid container, add these **Variable** entries under Edit → Add another Path, Port, Variable, Label or Device, then Apply. Keep your existing appdata and invoice-output mappings. New templates include the fields.

| Variable | Value |
|---|---|
| `SMTP_HOST` | Your provider's SMTP hostname |
| `SMTP_PORT` | Usually `587` for STARTTLS or `465` for SSL |
| `SMTP_SECURITY` | `starttls` or `ssl` |
| `SMTP_USERNAME` | Your mail account username |
| `SMTP_PASSWORD` | Your mail account/app password |
| `SMTP_FROM` | One sender email address permitted by the provider |

Credentials are read from container environment variables, not stored in the invoice database or returned by the API. Both username and password must be supplied together; leaving both blank supports a trusted TLS relay. TLS certificate verification is required with no unencrypted fallback. SMTP server acceptance does not prove inbox delivery: recipient filters, bounces and provider attachment limits still apply. Check your provider's SMTP settings and use an app password if required. Do not publish credential screenshots or export populated container templates publicly. The app has no login and must remain on your trusted LAN/WireGuard VPN.

History shows queued, sending, accepted by mail server, failed or delivery uncertain, with the original recipient. A saved invoice and its email job are committed together. Email failures do not roll back an already saved invoice or consume another number. Repeating a save with the same save token returns the existing invoice and never queues another email, even if the checkbox changes. The contact's saved email is checked again during creation; changed recipient details require refreshing the form. Later contact edits do not redirect queued mail. Unticked invoices cannot be emailed through a repeated save request.

Pending jobs resume on startup and the existing 30-second container health check. One persistent processing lease coordinates workers. Interrupted sending attempts become delivery uncertain after the 120-second lease; failed and uncertain emails are never retried automatically. **Retry email** in History requires confirmation of the original address and checking the recipient inbox/provider logs first, because another attempt may create a duplicate. Retry sends the original saved PDF without regenerating it or advancing any counter. Accepted-by-server emails do not have a resend button. The app allows 20 queue/retry requests per installation per hour and PDFs up to 20 MB before MIME encoding; the provider may impose a lower limit.

Latest-test removal is blocked while sending or delivery is uncertain. Since v0.29, the latest emailed test invoice can be removed with an explicit warning that deletion cannot recall its email; its counter is reset for reuse. Only use this for a test invoice. Removing a queued test invoice cancels its queued email. No bulk email, booking-app integration or automatic retry of uncertain sends is included. Tests use mocked SMTP; after configuring credentials, send a small test invoice to a contact address you control and verify the attachment arrives.

For v0.26 onward, commit reviewed text changes under `app/` and increment `app/VERSION`; the workflow overlays these files on the latest existing public archive, keeping its sanitized template. No new Word document or release ZIP upload is required. `scripts/package_release.py` can generate a complete local release ZIP from that same build context when needed. It never includes the private appdata template, database or credentials. The workflow checks the bundled email tests as well as actual container startup/PDF conversion before publishing.

## Connect Microsoft in Settings (v0.30)

Outlook.com/Hotmail personal accounts can use Microsoft Graph instead of password-based SMTP. The invoice app remains local-only with no login: keep its interface on a trusted LAN or WireGuard VPN. Microsoft sign-in does not add administrator login to the invoice app.

### One registration, separate servers

Reuse your existing Microsoft app registration's **Application (client) ID** on each server. It must support **personal Microsoft accounts**, have delegated Microsoft Graph **Mail.Send**, and have **Allow public client flows** enabled for device-code authentication. The app uses the consumers authority and MSAL's sign-in/offline authorisation support; it does not request permission to read mailbox contents. No client secret, public invoice-app URL, OAuth callback URL or inbound router port is required for this device-code flow. Registration changes or removal can affect all installations that use it. References: [Microsoft device-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) and [Graph sendMail permissions](https://learn.microsoft.com/en-us/graph/api/user-sendmail).

On each Unraid server retain its own existing appdata and invoice-output mappings, then configure:

| Variable | Value |
|---|---|
| `EMAIL_PROVIDER` | `microsoft_graph` |
| `MICROSOFT_CLIENT_ID` | The same Application (client) ID on both servers |
| `MICROSOFT_SENDER` | Optional: that server's intended mailbox address, or blank to use the connected mailbox |

Your dad signs in using his own Outlook.com account on his server; do not copy your token cache to his server. Only the public application ID is shared. Existing SMTP settings are retained and used when `EMAIL_PROVIDER=smtp`. Credentials are never committed to the repository; the public Unraid template leaves account-specific values blank.

### Connect or reconnect

1. Update the image and open **Settings → Microsoft account → Connect Microsoft account** (or Reconnect).
2. Open the Microsoft sign-in link displayed by the app and enter the code shown in Settings. Sign in to the intended personal Microsoft account and approve sending email. Only enter a code you personally started on your own invoice server.
3. Return to Settings. Check the mailbox shown and click **Use this account**. If MICROSOFT_SENDER is set, it must match that mailbox, ignoring case. For an alias mismatch, use the connected account's displayed address in the container setting or leave the setting blank; changing aliases is outside this release.
4. Send a small test invoice to an address you control, check History and confirm the PDF arrives. Automated tests mock Microsoft; a live check after deployment is still required.

The old working connection stays in place while a replacement sign-in is pending or awaiting mailbox confirmation. Cancel leaves it intact. A browser reload in the same tab can resume a pending code; a container restart or expired code requires starting sign-in again, while an already saved connection remains. Polling respects Microsoft's wait intervals and slow-down response. Only the browser session that started a code can view/confirm/cancel that attempt. One pending attempt is allowed per running installation, with a short start cooldown. Do not share device-code screenshots.

The interface shows the connected mailbox and does not refresh tokens just to display status. Refresh occurs when sending, so Microsoft can still require reconnection after consent revocation or token expiry. The existing `python /app/connect_microsoft.py` console command remains available for administrators.

### Disconnect and storage

**Disconnect** cancels pending sign-in and removes the stored token cache on that server. It does not delete invoices, recall emails, disconnect another server, or revoke the shared registration itself. To withdraw consent at Microsoft too, remove the application's access in the connected Microsoft account's app-permissions/privacy settings. Switching or disconnecting is blocked while invoice emails are queued or sending; let them complete or reach a failed state first, then use History's existing confirmed retry if appropriate.

Existing `/data/microsoft-token-cache.json` connections remain supported on upgrade. Token caches are protected by 0600 file permissions and atomic replacement under an inter-process lock; they are not encrypted at rest by this app. `/data/microsoft-account.json` stores the selected account and a connection revision so cancelled or superseded sign-ins cannot restore credentials. Pending sign-in codes/candidate tokens remain in process memory until confirmation and are never included in the general state response or logs. Back up appdata privately; its token cache grants mailbox sending access. Each server must have a separate appdata folder.

### Microsoft sign-in URL fix (v0.31)

v0.30 incorrectly replaced the provider's verification URL with a fixed device-login URL. v0.31 uses the URL Microsoft returns for that sign-in attempt, allowing personal-account codes to use `https://www.microsoft.com/link`. Only exact HTTPS Microsoft link/device-login URLs are accepted. Update and start a fresh connection attempt, then follow the displayed link. Existing saved mailbox connections are preserved.

## Visual invoice email template (v0.32)

Open **Settings → Invoice email template** to edit the subject and body without writing HTML. Select text and use bold/italic/underline, paragraph/headings, colour, lists, alignment, link/unlink, image, clear formatting, undo or redo. Images use a public HTTPS URL (initial display width 200 px); they are referenced by URL rather than embedded or fetched by the server, and recipients' email clients may block remote images. The PDF attachment is unchanged. The editor is local to the app with no CDN/editor-service account requirement.

The **Insert field** menu inserts into the last-focused subject or body. Supported fields are `{{invoice_number}}`, `{{client_name}}`, `{{company_name}}`, `{{client_email}}`, `{{invoice_date}}`, `{{due_date}}`, `{{amount_due}}`, `{{business_name}}`, `{{business_email}}`, `{{business_phone}}`, `{{business_address}}` and `{{payment_terms}}`. Client name prefers the saved contact person, then company. Dates use UK formatting and amount due subtracts the deposit. An unavailable due date is displayed as “As stated on the attached invoice”. Business name honours the BUSINESS_NAME container override.

**Preview email** uses synthetic sample information and your current draft, without sending email, saving the template or advancing a counter. It displays the subject, sandboxed HTML and generated plain-text alternative. **Save email template** sanitises and stores the template independently of business/payment settings and numbering. **Reload saved template** asks before discarding edits; **Restore default draft** requires Save to take effect. A version check prevents a stale window overwriting another saved template. Unsaved editor changes are kept when other app settings are reloaded.

The same template is used by SMTP and Microsoft Graph. A final rendered subject, HTML and plain text are saved with each new queued invoice in the same transaction as its PDF/number. Changes apply to later queued emails, not already queued messages or retries. Existing jobs without a saved email snapshot use the default template. Saving the same invoice token still does not send twice. Test deletion removes its email snapshot along with the invoice/email records.

HTML is cleaned using pinned nh3 before storage and again after safely escaping fixed-field values. Only basic email formatting, approved inline styles, HTTP(S)/single-address mailto links and HTTPS images are retained. Scripts, forms, frames, SVG, unsafe URLs, relative URLs, event handlers and unsupported styles are removed. Pasted HTML is cleaned on the server before inserting into the editor. The preview iframe has no script or same-origin privileges. Templates do not run Jinja, expressions or arbitrary code. Limits are 200 template subject characters, 30 KB body, 100 field references per part and 120 KB rendered HTML fragment. Email clients can render formatting differently; verify a test message with your provider after deployment. Automated transport tests mock SMTP/Graph and compare MIME alternatives and saved PDF bytes.

## Booking app integration (v0.33)

The companion No Alias Bookings v0.1.21 can review a completed enquiry and create an invoice, including a new contact and optional email. The integration is disabled until configured. Keep the invoice app private on LAN/VPN; do not expose its interface/API through the public bookings hostname. HTTP is suitable only on a trusted private network; use HTTPS across untrusted networks.

1. Generate a random shared secret locally, for example `python3 -c "import secrets; print(secrets.token_hex(32))"` (64 hex characters). Do not commit it or send it in chat.
2. Add `BOOKINGS_API_KEY` to the invoice container with that secret.
3. Add `INVOICE_API_KEY` with the same secret to bookings, and `INVOICE_APP_URL` set to the invoice container's private origin, e.g. `http://YOUR-UNRAID-LAN-IP:ACTUAL-INVOICE-HOST-PORT`. Use the actual invoice host port, which differs from bookings. On a shared user-defined Docker network, a resolvable container name and internal port 8080 can be used. `localhost` inside bookings refers to bookings itself.
4. Update both apps, preserving existing ports, appdata and invoice output mappings. Open Create invoice on a completed enquiry. Match/select a contact or create one, enter the agreed fee and deposit actually received, review, then confirm.

Existing contacts keep their saved name, address, email, numbering and terms. New contacts use main numbering/general terms; existing contact names are not silently overwritten. The billing address is separate from the event venue and is entered on the review screen. Client answers, booking prices and calendar events are not changed. No invoice/contact/email is created by previewing a review. Email is unchecked by default; it uses the invoice app's existing Microsoft/SMTP configuration and HTML template.

A stable installation/enquiry identity prevents duplicate invoices after double clicks, concurrent requests and lost responses. Refresh the booking's invoice screen to recover the result and delivery status. Retry failed/uncertain email in invoice History using the saved PDF and recipient. Deleting/cancelling a booking does not delete or recall its invoice. Removing a linked test invoice leaves a tombstone; replacement invoices must be managed manually in the invoice app. Back up/restore both appdata folders consistently: database rollback or cloning an installation can roll back or copy these identities.

The key grants the booking service access to invoice contacts and the narrow review/create/status API. Keep it private, rotate both copies together, and clear it to disable integration. No CORS access is enabled. Reviews are signed against current contact, numbering, business settings and email template; if these change, review again before creation. Requests are bounded and limited to 60 authenticated integration calls/minute.

## Email troubleshooting and attempt history (v0.34)

History now separates **Accepted by Microsoft/SMTP server — delivery not confirmed** from definite submission failure and uncertain outcome. Acceptance is the provider response to the app, not proof of inbox delivery or reading. For accepted messages that are missing, check the connected mailbox's Sent Items, delivery failure notices, then ask the recipient's IT team to check junk, quarantine and phishing filters. The app does not read mailbox contents, bounces or recipient security decisions and needs no new Microsoft permissions.

Expand **Email details** in History for the latest 50 attempts per invoice: provider, queue/start/finish times in Europe/London (BST/GMT), failure category, attempt reference, Microsoft HTTP/request IDs where supplied and numeric Retry-After when supplied. New metadata persists in appdata and is removed with a deleted test invoice. Older emails keep their existing status/PDF; detailed past attempts/provider identity are unavailable. A pending legacy email gains an attempt when it is next processed.

Container logs use invoice/attempt references and safe numeric codes/UUID correlation IDs. Raw SMTP/provider responses, exception messages, email bodies, attachments, passwords and tokens are excluded from new delivery diagnostics. Existing old log output is not retrospectively removed. Support references help locate an attempt; they do not prove delivery. SMTP recipient rejection and authentication/TLS failures are distinguished; Microsoft permissions, authentication, throttling and temporary provider failures have separate guidance. A provider rejection may still need investigation outside the app.

Retries remain explicit and limited as before. Check Sent Items/recipient delivery before retrying an uncertain attempt. Accepted messages cannot be retried from History. Numeric Retry-After is displayed as provider guidance, not an automatic retry schedule. No new container variables, storage mappings or mailbox permissions are required.

## Add a venue while invoicing (v0.35)

Choose an **Invoice to** contact, then select **Add new venue details...** at the top of a service row's venue dropdown. Enter the venue name (up to 200 characters) and address (up to 500 characters). Both are required. Complete the service and save the invoice as usual. Saving creates the venue in Venues, assigns it to the selected contact, enables that contact's assigned venues and uses the details on the invoice PDF. Multiple service rows can contain different new venues.

Preview generates a draft PDF without saving venues, changing assignments, using an invoice number or sending email. A failed invoice/PDF/email-queue save rolls back new venues and assignments along with the invoice. Retrying the same saved invoice does not create duplicate venues. The same new name/address for the same contact across rows is reused. A conflicting saved name/address or ownership is rejected: choose the existing venue or manage it in Venues. Existing records are never silently overwritten or reassigned through inline entry.

Changing the invoice contact resets Add new venue selection; select it again to review the retained draft fields for the new contact. Inline fields are ignored while a saved venue is selected. After saving, new venues are available in Venues and the selected contact's invoice dropdowns. Removing a saved test invoice does not remove its venue, which can be reused. No new container settings or storage changes are needed.

## Safe venue editing (v0.36)

In Venues, **Add venue** always creates a new record. A duplicate name (ignoring case and surrounding whitespace) is rejected instead of silently overwriting a saved venue. Choose distinct names for different properties, for example the property address; the Assigned contact field identifies its client.

Use a saved venue's **Edit** button to load that record. **Save venue changes** updates that record by ID, so changing the name/address keeps the same venue, assignment and invoice dropdown selection. Use **Cancel edit** to discard the edit and return to adding. A successful save returns the form to Add venue. If the venue changes in another window after opening Edit, the stale save is rejected; reopen Edit to review current values. A deleted venue ID cannot turn into a new record on save. Existing legacy names differing only by case are retained and can be renamed individually to distinct names.

Previously saved invoice details, PDFs and email snapshots remain unchanged. Existing data is not automatically renamed, merged or deleted. Inline Add new venue details on invoices still saves atomically with invoice completion. CSV import retains its explicit preview and update-by-name behavior. Contact editing is unchanged. No new settings or storage changes are required.
