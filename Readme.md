# Ping Bot for RemoteTerm
**MeshCore channel bot** for `#ping` and `#test`. Responds to `ping`, `test`, and `path` commands on incoming messages.
Runs inside [RemoteTerm for MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore) — a backend server with web UI, bot system, MQTT forwarding, and more. Bots are stored as Python files and managed via the API. The `bot(**kwargs)` function is the entry point — RemoteTerm calls it for every incoming message and sends the return value as a reply.

> **Note:** This bot is designed for use with the bot framework of [jkingsman/Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore) and requires its runtime environment.
Database path: `/opt/Remote-Terminal-for-MeshCore/data/meshcore.db`
---
## Commands
| Keyword | Channel(s) | Response |
|---------|------------|----------|
| `ping` | `#ping` | `Pong! @[Name] | N Hops` |
| `test` | `#test` | `ACK @[Name] | <path or "direct"> (N Hops) | SNR: X dB | RSSI: X dBm | Received at: HH:MM:SS` |
| `path` | `#ping` | Numbered list of all routing hops from sender to this node, split across multiple messages if needed |
---
## Configuration
`CHANNEL_CONFIG` and `BOT_PREFIXES` are defined as module-level constants at the top of the script and are the primary place to customize the bot's behavior.

### Adding or removing channels
Each entry in `CHANNEL_CONFIG` maps a channel name (including `#`) to a set of allowed keywords. To activate the bot in a channel, add it to the dict:

```python
CHANNEL_CONFIG = {
    "#ping": {"ping"},        # only responds to "ping"
    "#test": {"test"},        # only responds to "test"
    "#customroom": None,      # responds to all supported keywords
}
```

Channels not listed in `CHANNEL_CONFIG` are silently ignored.

### Restricting keywords per channel
The value for each channel entry controls which keywords the bot reacts to:

- **`{"ping"}`** — only `ping` triggers a response in this channel
- **`{"ping", "test"}`** — multiple keywords can be combined in a set
- **`None`** — no restriction; all supported keywords (`ping`, `test`, `path`) are active

### BOT_PREFIXES
`BOT_PREFIXES` defines the prefixes that identify outgoing bot replies. Any incoming message starting with one of these strings is silently dropped to prevent the bot from responding to itself:

```python
BOT_PREFIXES = ("pong!", "ack ", "path ", "(continues)")
```

If you add new reply formats, add their prefix here as well.

---
## Constants
- `DB_PATH` — path to RemoteTerm's SQLite database
- `MAX_HOPS = 10` — messages with more hops are silently ignored (anti-spam)
- `MAX_MSG_LENGTH = 220` — maximum character length per outgoing message (LoRa limit)
---
## Functions
### `resolve_path(path_hex, bytes_per_hop) → list[str]`
Converts the raw routing path (hex string from the radio) into human-readable node names.
- `path_hex` is a continuous hex string, e.g. `"aabbccdd11223344"` for two hops at 4 bytes each
- `bytes_per_hop` specifies how many bytes are encoded per hop (provided by the radio via `path_bytes_per_hop`)
- For each hop block, the public key is looked up in the `contacts` table using a `LIKE hex%` prefix match
- If no contact is found, the raw hex block is returned as `[aabbccdd]`
- On database error: returns `["[path unavailable]"]`
### `build_path_messages(name, resolved) → list[str]`
Formats the resolved hop names into one or more messages that fit within the LoRa length limit.
- Hops are numbered: `1. NodeA`, `2. NodeB`, …
- The first message starts with `Path @[Name]:`
- If another hop would exceed `MAX_MSG_LENGTH`, the current message is closed with `...` and a new one begins with `(Fortsetzung)`
- Returns a list of strings — RemoteTerm sends each entry as a separate message
### `get_rf_data(sender_timestamp) → (rssi, snr, received_at)`
Reads RSSI, SNR, and reception timestamp from the database for a received message.
- Looks up the `messages` table by `sender_timestamp` (unique sender-side timestamp)
- `paths` is a JSON array; the first entry contains the RF data of the direct receiver
- `received_at` is a Unix timestamp (formatted as UTC time in the reply)
- Returns all three values as `None` if the timestamp is missing or a DB error occurs
### `test` Command
When a sender writes `test` in a configured channel, the bot replies with a full diagnostic line:

```
ACK @[Name] | <path_str> | SNR: X dB | RSSI: X dBm | Received at: HH:MM:SS
```

The individual fields are assembled as follows:

- **`path_str`** — if the message was relayed, the raw hex blocks for each hop are listed comma-separated followed by the hop count, e.g. `aabbccdd,11223344 (2 Hops)`. For a direct connection, `direct (0 Hops)` is used.
- **SNR / RSSI** — read from the database via `get_rf_data()` using the sender timestamp. Both fields are optional and omitted if not available.
- **Received at** — UTC reception time (`HH:MM:SS`), also from the database. Omitted if not available.

### `path` Command
When a sender writes `path` in a configured channel, the bot resolves the full routing path of the incoming message and replies with a numbered list of all intermediate nodes between the sender and this node.

- The raw path is read from the `path` parameter (hex string provided by the radio firmware)
- `resolve_path()` converts each hop block into a human-readable node name by looking up the contact's public key in the database
- Unknown nodes are shown as their raw hex value, e.g. `[aabbccdd]`
- `build_path_messages()` formats the result into one or more messages, each prefixed with `Path @[Name]:` — if the full list exceeds `MAX_MSG_LENGTH`, it is split across multiple messages with `(Fortsetzung)` continuations
- If the message arrived directly (no hops), the path will be empty

### `bot(**kwargs) → str | list[str] | None`
Entry point — called by RemoteTerm for every message.
**Incoming parameters:**
| Parameter | Description |
|-----------|-------------|
| `sender_name` | Display name of the sender |
| `message_text` | Message content |
| `channel_name` | Channel name including `#`, e.g. `#ping` |
| `is_outgoing` | `True` for messages sent by this node |
| `path` | Routing path as hex string (empty for direct connections) |
| `path_bytes_per_hop` | Bytes per hop as reported by the radio firmware |
| `sender_timestamp` | Sender-side timestamp (used for DB lookup) |
**Processing order:**
1. Immediately ignore outgoing messages (`is_outgoing`)
2. Ignore own bot replies based on `BOT_PREFIXES` — prevents infinite loops
3. Check channel: only configured channels are processed
4. Optionally restrict allowed keywords per channel (`CHANNEL_CONFIG`)
5. Calculate hop count and check against `MAX_HOPS`
6. Build and return the appropriate reply based on keyword (`ping` / `test` / `path`)
**Return value:** `None` = no reply, `str` = single message, `list[str]` = multiple messages sent in sequence
