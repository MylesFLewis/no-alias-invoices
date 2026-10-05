# Invoice app repository

Build versioned Docker images for a local invoice app and update them through Unraid. Public releases contain blank settings, no saved contacts and a sanitized Word template. Your personal data belongs in the private `/data` volume.

## First GitHub setup

Create a public repository named `no-alias-invoices`, with default branch `main`. Commit this repository's contents at its root, including `.github/workflows/publish.yml`, `scripts`, `unraid` and `releases`. Do not upload earlier private release ZIPs.

The workflow extracts the highest numeric release in `releases`, builds it, checks startup and PDF conversion, then publishes `ghcr.io/mylesflewis/no-alias-invoices:latest` and a version tag. The release ZIP contains the complete sanitized app source and is the build input.

After the first successful run, open your profile's Packages page, select the image, open Package settings and change its visibility to **Public**. Public repositories do not automatically make newly published container packages public. No Docker Hub account or personal access token is needed for the build.

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

The bundled XML is a fallback: replace `YOUR_GITHUB_USERNAME` with your lowercase GitHub username before installing it. Use the image repository name if you choose a different repository name.

## Later updates

Upload a sanitized `no-alias-invoices-v0.5.zip` (or later) into the repository's `releases` folder using **Add file → Upload files**, and commit it to `main`. Each ZIP contains a top-level `no-alias-invoices` folder and a VERSION file matching its filename. Keep only public-safe source in release ZIPs; do not include a database or private template.

Wait for **Build invoice image** in Actions to succeed. Then in Unraid's Docker tab select **Check for Updates**, and update this container. Always use `:latest` for this flow. A specific `:v0.4` tag stays on that version.

A failed build leaves the published `latest` image in place. To roll back, edit the container's Repository field to a previous version tag and Apply. Appdata stays on the server.

## Local operation

The web app has no login. Keep it on your trusted LAN or WireGuard VPN. No public router port or reverse proxy is required. The interface uses no external assets. PDF conversion runs in the container.

Source: [GitHub container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
