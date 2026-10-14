# Stack Up Finance frontend

The frontend is a React/Vite application. The same UI can be built for the
website and packaged for iOS and Android with Capacitor.

## Native app setup

1. Install Node.js, Android Studio and the Android SDK. Building the iOS app
   requires macOS with Xcode.
2. Create `frontend/.env.mobile.local` with the public HTTPS URL of the deployed
   FastAPI service:

   ```dotenv
   VITE_API_BASE_URL=https://your-public-api-host
   ```

   Use the backend URL only; do not add API keys or other secrets. The local
   file is ignored by Git. The value is embedded in the app and is not secret.
   Mobile builds reject non-HTTPS, malformed, and relative API URLs.
3. In the backend service's `FRONTEND_URL` setting, keep the existing website
   origin and add `https://localhost` as another comma-separated allowed
   origin. Redeploy the backend before testing native sign-in; the app uses
   credentialed requests and the backend's existing secure session cookies.
4. From this directory, build and sync the Android project:

   ```powershell
   npm ci
   npm run build:mobile
   npm run cap:sync
   npm run cap:open:android
   ```

5. On a Mac with Xcode, use the same build and sync commands, then run
   `npm run cap:open:ios`. Configure signing and a store archive in Xcode.

Capacitor project identifiers are set to `app.stackupfinance.site`; use that
same identifier when configuring both stores. Do not change it after the first
store release.

The native app bundles the frontend but still requires an internet connection
to reach the deployed backend. Store submission also requires production app
icons/screenshots, privacy disclosures and links, signed release builds, and
developer accounts. Verify authentication, PDF selection/upload, and account
deletion on physical devices before submission.
