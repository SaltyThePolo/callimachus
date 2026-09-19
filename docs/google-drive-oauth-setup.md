# Get the Google Drive desktop OAuth JSON

Allow about 10–15 minutes. You need a Google account with Drive and permission to create or configure a Google Cloud project.

Callimachus uses an **OAuth client of type Desktop app**. The downloaded JSON identifies that client; signing in later authorizes your Drive account. An API key or a service-account JSON is not a substitute.

## 1. Select a project and enable Drive API

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Use the project selector to create a project, such as `Callimachus`, or select an existing project you manage.
3. Open the [Google Drive API page](https://console.cloud.google.com/apis/library/drive.googleapis.com) and check that the same project is selected.
4. Click **Enable**. If the API is already enabled, continue.

Keep this project selected throughout the remaining steps.

## 2. Configure the consent screen

Open **Google Auth platform → Branding**. For a new configuration, click **Get started** and provide:

- **App name:** `Callimachus`.
- **User support email** and **Contact information:** an email address you control, entered only in Google Cloud.
- **Audience:** choose **External** for a personal Google account. Use **Internal** only when available and access should be limited to your Workspace organization.

Review Google's terms and finish the setup if you accept them. For an existing configuration, review its Branding and Audience settings instead.

For an External app in testing mode, open **Audience → Test users → Add users**, add the Google account you will use with Drive, and save. Public publishing is not needed for this test setup.

In **Data Access → Add or Remove Scopes**, add the scope Callimachus requests and save:

```text
https://www.googleapis.com/auth/drive.file
```

This scope limits access to files available to this OAuth app. See Google's [consent-screen configuration guide](https://developers.google.com/workspace/guides/configure-oauth-consent).

## 3. Create the desktop client and download its JSON

1. Open **Google Auth platform → Clients** in the same project.
2. Click **Create Client**.
3. Set **Application type** to **Desktop app** and give it a name, such as `Callimachus Desktop`.
4. Click **Create**, then download the client JSON using the download option for the new client.

Follow the [official desktop OAuth quickstart](https://developers.google.com/workspace/drive/api/quickstart/python) if the console labels differ. Keep the downloaded file on your computer; do not paste its contents into an issue or chat.

## 4. Store the file locally

From the Callimachus repository root, create a private credentials directory:

```sh
mkdir -p credentials
chmod 700 credentials
```

Move the downloaded JSON into that directory and name it `google-client.json`. Then restrict file permissions:

```sh
chmod 600 credentials/google-client.json
```

Create `.env` from `.env.example` if you do not already have one. Edit these settings in your existing `.env`, preserving its other values:

```dotenv
CALLIMACHUS_DESTINATION=drive
CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE=./credentials/google-client.json
CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID=
```

Leaving the folder ID empty lets Callimachus create its own folder. Relative paths resolve from the directory where you run the command.

**This repository is public.** Keep the downloaded JSON, `.env`, authorization tokens, recordings, and meeting content out of commits, issues, screenshots, and logs. The repository ignores `credentials/`, `.env`, `.callimachus/`, and `archive/`. Never force-add these files. Check the ignore rules before staging changes:

```sh
git check-ignore credentials/google-client.json .env
git status --short
```

The first command should print both paths. If it does not, stop before staging credentials and check their location and the ignore rules. Ignoring a file does not remove it from Git if it was already tracked.

## 5. Authorize Callimachus

From the repository root, run:

```sh
uv run callimachus login drive
```

Complete the browser sign-in with the account configured above and review the requested access. On success, Callimachus saves authorization in private local state and prints the Drive archive folder link. This command authorizes Drive and prepares the folder; it does not upload meeting archives.

You can then run:

```sh
uv run callimachus doctor
```

`drive_credentials=present` confirms that the local credential file exists. It does not verify remote authorization or successful uploads. Run `uv run callimachus sync` when ready to archive meetings and send the local archive history to Drive.

## Common setup problems

| Symptom | What to check |
| --- | --- |
| Client JSON missing | Confirm the file exists at the path in `.env` and run from the repository root. |
| Wrong credential type | Create an OAuth **Desktop app** client, rather than a web client, API key, or service account. |
| Test-user access denied | For an External app in testing, add the sign-in account under **Audience → Test users**. Organization policies may also restrict access. |
| Drive API disabled | Enable Drive API in the project that owns the downloaded client. |
| Authorization expires later | Run `uv run callimachus login drive` again. Testing-mode refresh tokens can expire after seven days; see [Google's token-expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration). |
