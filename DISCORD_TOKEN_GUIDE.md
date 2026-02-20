# How to Get Your Discord User Token

This guide explains how to extract your personal Discord token so the platform can read messages from servers where you are a member (no admin access needed).

---

## Important Notes

- Your Discord token is like a password — **never share it with anyone**.
- Using a user token to automate actions technically violates Discord's Terms of Service. Use at your own discretion.
- This platform uses your token in **read-only mode** to listen for messages. It does not send messages, modify channels, or perform any write actions.
- If you ever suspect your token is compromised, **change your Discord password** immediately — this invalidates all existing tokens.

---

## Method 1: Network Tab (Recommended)

1. Open **Discord in your browser** at [discord.com/app](https://discord.com/app)
2. Press **F12** (or `Ctrl+Shift+I` / `Cmd+Option+I` on Mac) to open Developer Tools
3. Go to the **Network** tab
4. In the filter box, type `api` to narrow the list
5. Click on any channel or server in Discord to trigger network requests
6. Click on any successful request (e.g. one containing `messages` or `@me`)
7. In the **Headers** panel, scroll to **Request Headers**
8. Find the **`Authorization`** header — the value is your token

```
Authorization: your_token_here
```

Copy that value (without the `Authorization:` prefix).

---

## Method 2: Console Script

1. Open Discord in your browser
2. Press **F12** to open Developer Tools
3. Go to the **Console** tab
4. Paste this script and press Enter:

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

5. Your token will be printed in the console. Copy it.

---

## Method 3: Desktop App (Windows/Mac)

1. Open the Discord **desktop app**
2. Press `Ctrl+Shift+I` (Windows) or `Cmd+Option+I` (Mac) to open DevTools
3. Follow the same steps as Method 1 (Network tab) or Method 2 (Console)

---

## How to Get Channel IDs

1. In Discord, go to **User Settings** → **Advanced** → Enable **Developer Mode**
2. Right-click any text channel
3. Click **Copy Channel ID**
4. Paste it into the platform's Data Sources configuration

Multiple channels can be specified as a comma-separated list:
```
1234567890123,9876543210987
```

---

## Using the Token in PhoenixTrade

### Via Dashboard
1. Go to **Data Sources** → **Add Source**
2. Select **Discord** as platform
3. Choose **User Token** as authentication method
4. Paste your token
5. Enter channel IDs (or leave blank to auto-discover)
6. Click **Save**

### Via Environment Variable (for local dev)
```bash
DISCORD_USER_TOKEN=your_token_here
DISCORD_TARGET_CHANNELS=123456789,987654321
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Token doesn't work | Make sure you copied the full token string. Try logging out and back in to Discord, then re-extract. |
| "Invalid token" error | Your token may have expired. Change your Discord password (which rotates tokens) and re-extract. |
| Can't see messages from a channel | Verify you have read access to that channel as a member. Check the Channel ID is correct. |
| Rate limited | The platform handles rate limits automatically. If persistent, reduce the number of monitored channels. |

---

## Security

Your token is encrypted at rest using Fernet symmetric encryption before being stored in the database. It is only decrypted in memory when the Discord ingestor service needs to connect. The encryption key is managed via the `CREDENTIAL_ENCRYPTION_KEY` environment variable.
