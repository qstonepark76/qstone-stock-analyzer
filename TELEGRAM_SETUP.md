# Q Stone Park Telegram integration (phase 1: collection + shadow analysis)

## Scope
- Public channels: `@bumgore`, `@globalmktinsight`, `@HanaResearch`
- Hourly collection through GitHub Actions.
- Text/captions and message metadata are stored; media files are not downloaded.
- Rule-based evidence tags are generated in shadow mode.
- **The existing seven-category / 100-point score is not changed in this phase.**

## Required GitHub Actions secrets
Add these repository secrets under Settings -> Secrets and variables -> Actions:
- `TELEGRAM_API_ID`: integer from https://my.telegram.org
- `TELEGRAM_API_HASH`: API hash from https://my.telegram.org
- `TELEGRAM_SESSION`: Telethon StringSession generated locally using `scripts/setup_telegram_session.py`

Never paste the API hash, login code, phone number, or session string into ChatGPT or commit them to Git. The session string grants account access and must be protected like a password.

## Generate TELEGRAM_SESSION locally
1. Clone the repository and install dependencies: `pip install -r requirements.txt`.
2. Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` as local environment variables.
3. Run: `python scripts/setup_telegram_session.py`.
4. Complete the Telegram login prompt locally.
5. Copy the resulting session string directly into the GitHub Actions secret `TELEGRAM_SESSION`. Do not send it to anyone.

## First run
After all three secrets are saved, open Actions -> "Q Stone Park Telegram Hourly Collection" -> Run workflow.
The workflow collects up to the latest 500 unseen messages per channel on the first run, then only messages newer than the last saved message ID. It commits:
- `data/telegram_messages.json`
- `data/telegram_state.json`
- `data/telegram_analysis.json`
- `data/telegram_collection_status.json`

## Limitations and safeguards
- The Telegram account must already have access to each channel. Public channel visibility does not bypass Telegram's access controls or rate limits.
- First-run history is capped at 500 messages per channel to keep the initial import bounded; this can be increased later after testing.
- Media files are not downloaded. Posts with captions retain their text/caption; image/PDF interpretation is a later phase.
- Keyword extraction is a screening aid, not an AI fact-check. It may miss aliases and can misclassify context.
- Telegram information remains shadow-only until evidence quality and historical recommendation performance are validated.
