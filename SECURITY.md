# Security Policy

## Credentials

- Never commit Binance API keys, API secrets, cookies, tokens, database files, or
  trained artifacts containing private data.
- Use a Binance API key with the minimum permissions required. Disable
  withdrawals and restrict the key by IP where possible.
- Prefer Testnet and paper mode while evaluating this project.
- The dashboard clears the API key and secret input after a connection attempt.
  Credentials are held in process memory and are not written to SQLite.

## Reporting a problem

Do not publish credentials in an issue or pull request. For a private report,
contact the repository owner through GitHub's private security advisory flow.
