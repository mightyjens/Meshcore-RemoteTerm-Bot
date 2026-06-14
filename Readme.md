# MeshCore RemoteTerm Ping/Test/Path Bot

A example bot for the Python bot framework provided by
[jkingsman/Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore).

This bot responds to diagnostic keywords (`ping`, `test`, `path`) in configurable MeshCore
channels and returns RF metrics, hop counts, and resolved routing paths — useful for network
testing and coverage verification.

---

## Features

- **`ping`** — Replies with a pong message and the number of hops
- **`test`** — Replies with hop count, SNR, RSSI, and message reception timestamp
- **`path`** — Replies with the fully resolved hop-by-hop routing path (node names looked up
  from the RemoteTerm database); automatically splits into multiple messages if the path
  exceeds the MeshCore message length limit
- **Per-channel keyword filtering** — Each channel can be restricted to specific keywords
- **Hop limit** — Ignores messages from nodes beyond a configurable maximum hop count
- **Loop protection** — Ignores own outgoing messages and typical bot reply prefixes to
  prevent infinite reply loops

---

## Requirements

- [Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore)
  installed and running
- A MeshCore companion radio connected via serial, TCP, or BLE
- Python 3.11+ (provided by the RemoteTerm environment)
- No additional dependencies — only Python standard library modules are used (`sqlite3`,
  `json`, `re`, `datetime`)

---

## Installation

1. Open the RemoteTerm web interface (`http://<your-server>:8000`)
2. Navigate to the **Bots** section (Settings -> MQTT & Automation -> Add Integration -> Python Bot)
3. Create a new bot and paste the contents of `bot.py` into the code editor
4. Save and enable the bot

The bot code is executed directly by RemoteTerm's bot framework on every incoming message.
No separate process or service is required.

---

## Configuration

All configuration is located at the top of `bot.py`:

```python
# Path to the RemoteTerm SQLite database
DB_PATH = "/opt/Remote-Terminal-for-MeshCore/data/meshcore.db"

# Maximum hop count – messages from nodes further away will be ignored
MAX_HOPS = 10

# Maximum character length per MeshCore message
MAX_MSG_LENGTH = 220

# Channel configuration:
# Key   = exact channel name as in MeshCore (including #)
# Value = set of allowed keywords, or None to allow all keywords
CHANNEL_CONFIG = {
    "#customchannel": None,     # all keywords allowed
    "#ping":          {"ping"}, # only "ping"
    "#test":          {"test"}, # only "test"
}
```

### Adding channels

Add an entry to `CHANNEL_CONFIG` with the exact channel name (including `#`) as used in
MeshCore. Set the value to `None` to allow all keywords, or to a set of strings to restrict
which keywords trigger a response in that channel:

```python
CHANNEL_CONFIG = {
    "#mychannel":  None,              # responds to ping, test, path
    "#ping":       {"ping"},          # responds to ping only
    "#diagnosis":  {"test", "path"},  # responds to test and path
}
```

### Adjusting the hop limit

Set `MAX_HOPS` to control the maximum number of relay hops a message may have traveled.
Messages arriving via more hops than this value are silently ignored:

```python
MAX_HOPS = 10  # ignore messages more than 10 hops away
```

### Adjusting the message length limit

`MAX_MSG_LENGTH` controls when path responses are split into multiple messages. The default
of 220 characters is a conservative value that works reliably across MeshCore firmware
versions:

```python
MAX_MSG_LENGTH = 220
```

---

## Keyword Reference

All keywords are matched **case-insensitively** and as substrings, so `"Ping"`, `"PING"`,
and `"send a ping please"` all trigger the `ping` handler.

### `ping`

```
→ Pong! @[SenderName] | 3 Hops
```

### `test`

```
→ ACK @[SenderName] | 3 Hops | SNR: 12.5 dB | RSSI: -78 dBm | Received at: 14:32:07
```

If the message arrived directly (no relay hops):

```
→ ACK @[SenderName] | direct (0 Hops) | SNR: 14.0 dB | RSSI: -51 dBm | Received at: 11:20:31
```

### `path`

Single message (short path):

```
Path @[SenderName]:
1. Region-Alpha-Repeater
2. Some-Solar-Node
3. Region-Beta-Repeater
```

Split across two messages (long path or long node names):

**Message 1:**
```
Path @[SenderName]:
1. Region-Alpha-Repeater
2. Some-Solar-Node
3. Region-Beta-Repeater
...
```

**Message 2:**
```
(continued)
4. [a1b2c3d4]
5. Region-Gamma-Repeater
```

Unknown nodes (not present in the RemoteTerm database) are shown as their hex short form,
e.g. `[82bf61d3]`.

---

## How Path Resolution Works

MeshCore encodes routing paths as concatenated shortened public key hashes. With
`path.hash.mode 1` (the default for most networks), each hop is represented by 2 bytes
(4 hex characters).

The bot splits the raw hex path string into individual hop segments and looks each one up
in the RemoteTerm `contacts` table using a `LIKE` prefix match against the full public key:

```sql
SELECT name FROM contacts WHERE public_key LIKE 'a1b2%' LIMIT 1
```

This allows node names to be resolved without storing a separate hash-to-name mapping.

---

## How RF Metrics Are Retrieved

RSSI, SNR, and reception timestamps are not passed directly to the bot via kwargs.
Instead, the bot queries the RemoteTerm `messages` table using the `sender_timestamp`
field, which is available in the bot kwargs and unique enough for a reliable lookup:

```sql
SELECT paths, received_at FROM messages
WHERE sender_timestamp = ? AND outgoing = 0
ORDER BY id DESC LIMIT 1
```

The `paths` column contains a JSON array with per-path RF data:

```json
[{"path": "a1b2...", "rssi": -78, "snr": 12.5, "received_at": 1781437024}]
```

---

## Loop Protection

The bot uses two independent mechanisms to prevent infinite reply loops:

1. **`is_outgoing` guard** — RemoteTerm sets this flag on messages sent by the bot itself.
   The bot returns `None` immediately for any outgoing message.

2. **`BOT_PREFIXES` guard** — The bot checks whether the incoming message starts with a
   known bot reply prefix and ignores it if so:

```python
BOT_PREFIXES = ("pong!", "ack ", "path ", "(continued)")
```

This prevents loops even if another bot on the network replies to the bot's own responses.

---

## Bot Framework Notes

This bot is designed for the RemoteTerm bot framework. Key framework characteristics:

- The `bot(**kwargs)` function is called for **every incoming message**, including channel
  messages and direct messages
- Return `None` to send no reply
- Return a `str` to send a single reply
- Return a `list[str]` to send multiple replies in order
- Bots execute arbitrary Python via `exec()` with full `__builtins__` — only deploy in
  trusted network environments
- Full bot framework documentation and the `kwargs` reference are available in the
  RemoteTerm repository: [jkingsman/Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore)

---

## License

MIT
