# Home Airspace for Fire TV

A small Android app that shows your Home Airspace site full screen on an Amazon Fire TV (or any Android TV). It is a wrapper around the website: the map, aircraft list, and TV mode all come from your Render service, so website updates reach the TV without reinstalling the app.

What the app adds over the Silk browser:

- Its own tile on the Fire TV home screen; no address bar or bookmarks.
- The screen stays on while the app is open.
- TV mode is always on. The arrow keys move between buttons and aircraft; **Select** presses; **Back** leaves the app.
- **Menu** (☰) on the remote: **Reload** or **Change site address**.
- If the site can't be reached (no internet, or Render waking up) it shows a message and retries every 15 seconds.

The app contains no site address, password, or keys. On first launch it asks for your site address and stores it on the TV. Sign-in cookies stay on the TV, so **Remember this device** lasts its full 30 days. The app only opens pages on your site; links elsewhere are ignored.

## One-time setup: signing key

Android only installs an update over an existing app if both are signed with the same key. The GitHub Actions build signs the app with a key stored in the repository's secrets.

1. On GitHub, open the repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Add `FIRETV_KEYSTORE_BASE64` with the contents of the key file (a long single line of text).
3. Add `FIRETV_KEYSTORE_PASSWORD` with the key's password.
4. Open **Actions** → **Fire TV app** → **Run workflow**.

Also keep a copy of both values in your password manager. If the key is lost, you can make a new one, but the TV app must then be uninstalled and reinstalled once (and you sign in again).

To make a new key yourself (needs Java's `keytool`):

```sh
keytool -genkeypair -storetype PKCS12 -keystore release.p12 -alias homeairspace \
  -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=Home Airspace TV"
base64 -w0 release.p12    # macOS: base64 -i release.p12
```

The alias must be `homeairspace`, and the key password must equal the keystore password.

Without the secrets, the build still runs (handy for checking it compiles) but signs with a temporary key and only attaches the APK to the workflow run instead of publishing it.

## Install on the Fire TV

Each successful signed build replaces `home-airspace.apk` on the **firetv-latest** release:

`https://github.com/ckelle1635-bot/adsb-away/releases/download/firetv-latest/home-airspace.apk`

1. On the Fire TV, install **Downloader** (by AFTVnews) from the Appstore.
2. Allow it to install apps: **Settings → My Fire TV → Developer Options → Install unknown apps → Downloader → On**. If you don't see Developer Options, open **Settings → My Fire TV → About** and press Select on the device name seven times.
3. In Downloader, enter the APK address above and choose **Install**. Delete the downloaded file when Downloader offers.
4. Open **Home Airspace** from **Apps** (move it to the home row if you like), enter your site address such as `your-service.onrender.com`, and sign in with **Remember this device** ticked.

To update, repeat step 3. Your address and sign-in are kept.

Typing the long GitHub address with the remote is tedious; the Amazon Fire TV phone app gives you a phone keyboard.

## Build locally (optional)

With the Android SDK and Gradle 8.14 installed: `gradle -p firetv assembleRelease`. Set `FIRETV_KEYSTORE` (path to the `.p12` file) and `FIRETV_KEYSTORE_PASSWORD` to sign with the release key.
