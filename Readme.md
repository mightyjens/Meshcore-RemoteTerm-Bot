# Ping Bot
**MeshCore channel bot** for `#ping` and `#test`. Responds to `ping` and `test` commands on incoming messages.
Runs inside [RemoteTerm for MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore) — a backend server with web UI, bot system, MQTT forwarding, and more. Bots are stored as Python files and managed via the API. The `bot(**kwargs)` function is the entry point — RemoteTerm calls it for every incoming message and sends the return value as a reply.

> **Note:** This bot is designed for use with the bot framework of [jkingsman/Remote-Terminal-for-MeshCore](https://github.com/jkingsman/Remote-Terminal-for-MeshCore) and requires its runtime environment.
Database path: `/opt/Remote-Terminal-for-MeshCore/data/meshcore.db`
---
## Commands
| Keyword | Channel(s) | Response |
|---------|------------|----------|
| `ping` | `#ping` | `Pong! @[Name] | N Hops` |
| `test` | `#test` | `ACK @[Name] | path (hex) | SNR | RSSI | time UTC` |
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
6. Build and return the appropriate reply based on keyword (`ping` / `test`)
**Return value:** `None` = no reply, `str` = single message, `list[str]` = multiple messages sent in sequence
