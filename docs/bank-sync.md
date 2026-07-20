# Direct bank sync

The dashboard can connect US bank accounts through Plaid Link and import up to
24 months of transactions. Bank usernames and passwords are entered only in
Plaid's hosted UI. Plaid access tokens are encrypted before being stored in the
local SQLite database.

## Setup

1. Create a Plaid developer account and copy the client ID and Sandbox secret.
2. Copy `.env.example` to `.env` and replace all placeholder values. The app
   does not read `.env` automatically, so load those variables in the shell or
   your process manager before starting Streamlit.
3. Start with `PLAID_ENV=sandbox`. In the app, open **Import**, select
   **Connect a bank**, and use Plaid's Sandbox credentials.
4. Select **Sync** after connecting. The first sync can take time while Plaid
   prepares historical transactions; later syncs use an incremental cursor.

For PowerShell, variables can be loaded for the current terminal with:

```powershell
$env:PLAID_CLIENT_ID="..."
$env:PLAID_SECRET="..."
$env:PLAID_ENV="sandbox"
$env:PLAID_TOKEN_ENCRYPTION_KEY="use-a-long-random-secret"
uv run streamlit run app.py
```

Never commit `.env`, Plaid secrets, access tokens, or the local `data/`
directory. Changing `PLAID_TOKEN_ENCRYPTION_KEY` makes existing connections
unreadable; disconnect and reconnect them if the key is rotated.

Production access requires enabling the Transactions product and completing
Plaid's production approval process. Change both the secret and `PLAID_ENV` to
production only after approval.
