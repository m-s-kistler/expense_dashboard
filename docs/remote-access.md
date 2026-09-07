# Browser access with Tailscale Funnel

The dashboard requires Google login, a verified owner email, and an unexpired
Google identity before opening its database. Missing configuration blocks access,
including local access. No financial information is displayed on the login page.

Only the hosting Windows PC needs Tailscale. Visitors use a normal browser.
The PC must remain awake with Streamlit and Tailscale running.

## One-time account setup

1. Install Tailscale and sign in on the hosting PC.
2. Obtain the device hostname without publishing the app:
   ```powershell
   $Device = & 'C:\Program Files\Tailscale\tailscale.exe' status --json | ConvertFrom-Json
   $Device.Self.DNSName.TrimEnd('.')
   ```
3. In [Google Auth Platform](https://console.cloud.google.com/auth/overview),
   create/select a project. Configure branding as Finance Dashboard, choose an
   External audience, and add `mskistler@gmail.com` as a test user.
4. Create an OAuth client of type **Web application**. Register
   `https://YOUR-DEVICE.YOUR-TAILNET.ts.net/oauth2callback` as an authorized
   redirect URI, using the exact hostname from step 2. Only request basic
   OpenID identity scopes (openid, email, profile).
5. Download the client's JSON to a local folder. Do not paste the client secret
   into chat or commit it. Import it from the project folder:
   ```powershell
   .venv\Scripts\python.exe scripts\configure_google_login.py 'C:\path\client_secret.json' --public-url 'https://YOUR-DEVICE.YOUR-TAILNET.ts.net'
   ```
   This creates `.streamlit/secrets.toml`, excluded from Git, and a random
   signing secret. It restricts dashboard access to `mskistler@gmail.com`.
6. Restart the application using `scripts\start_app.ps1`. Check that an
   unsigned-in session sees only the Google login page.
7. Once the authentication gate is checked, enable Funnel:
   ```powershell
   & 'C:\Program Files\Tailscale\tailscale.exe' funnel --bg http://127.0.0.1:8501
   ```
   Complete Tailscale's HTTPS/Funnel enablement link if prompted.
8. Open the supplied HTTPS URL. Verify owner login works, signing out hides
   the data, and another Google account cannot access the dashboard. Test
   from a phone using cellular data with no Tailscale client connected.

## Operation

Google login returns to the public hostname configured in secrets, even when
initiated from localhost. Use the public URL for normal sign-in.
The app checks identity expiry on reruns; sign in again when a session expires.
Funnel itself does not authenticate visitors. Never remove the app's login gate
while Funnel is enabled. Do not expose data, logs, or project folders as static files.

Stop public access with:
```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' funnel --https=443 off
```

The background Funnel configuration survives restarts, but Streamlit still needs
to run. Windows unattended operation is a separate Tailscale setting. The SQLite
database remains in `data/`; continue backing it up locally.

References: [Streamlit Google authentication](https://docs.streamlit.io/develop/tutorials/authentication/google),
[Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).
