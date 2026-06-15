import sqlite3
import json
import re
from datetime import datetime, timezone

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Path to the RemoteTerm SQLite database
DB_PATH = "/opt/Remote-Terminal-for-MeshCore/data/meshcore.db"

# Maximum hop count – messages from nodes further away will be ignored
MAX_HOPS = 10

# Maximum character length per MeshCore message
MAX_MSG_LENGTH = 220

# Maximum hop count for detailed path output in test response
MAX_HOPS_DETAIL = 5

# Channel configuration:
# Key   = exact channel name as in MeshCore (including #)
# Value = set of allowed keywords, or None to allow all keywords
#
# Supported keywords: "ping", "test", "path"
# Example: {"ping"} → bot only responds to "ping" in this channel
#          None     → bot responds to all keywords
CHANNEL_CONFIG = {
    "#customchannel": None,     # all keywords allowed
    "#ping":          {"ping"}, # only "ping"
    "#test":          {"test"}, # only "test"
}


# ──────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────

def is_keyword(msg: str, keyword: str) -> bool:
    """
    Returns True only if the message consists solely of the keyword,
    optionally preceded by ! or / as a command prefix.
    Prevents triggering on keywords embedded in sentences.

    Examples:
        "ping"    → True
        "!ping"   → True
        "/ping"   → True
        "ping me" → False
        "Path @[C3PO]: 1. Node ..." → False

    Args:
        msg:     Stripped and lowercased message text
        keyword: Keyword to match (e.g. "ping", "test", "path")

    Returns:
        True if the message is exactly the keyword (with optional prefix)
    """
    return bool(re.fullmatch(rf'[!/]?{re.escape(keyword)}', msg.strip()))


def resolve_path(path_hex: str, bytes_per_hop: int) -> list[str]:
    """
    Resolves a hex-encoded routing path into readable node names.

    MeshCore encodes the path as concatenated shortened public key hashes.
    With path.hash.mode 1, each hop is 2 bytes (4 hex characters).
    The function splits the path into hop segments and looks up the
    corresponding node name in the RemoteTerm database (table: contacts).

    Unknown hops are returned as "[abcd]" (hex short form).

    Args:
        path_hex:      Hex string of the routing path (e.g. "a1b2c3d4")
        bytes_per_hop: Bytes per hop segment (1, 2, or 3 depending on path.hash.mode)

    Returns:
        List of node names in hop order.
        On error: ["[path unavailable]"]
    """
    if not path_hex or not bytes_per_hop:
        return []
    if not re.fullmatch(r'[0-9a-fA-F]+', path_hex):
        return []

    hex_per_hop = bytes_per_hop * 2
    hops = [path_hex[i:i+hex_per_hop] for i in range(0, len(path_hex), hex_per_hop)]

    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            names = []
            for hop in hops:
                # LIKE search on the beginning of the public key (short form match)
                cur.execute(
                    "SELECT name FROM contacts WHERE public_key LIKE ? LIMIT 1",
                    (hop + "%",)
                )
                row = cur.fetchone()
                names.append(row[0] if row else f"[{hop}]")
            return names
    except Exception:
        return ["[path unavailable]"]


def build_path_messages(sender_name: str, resolved: list[str]) -> list[str]:
    """
    Builds one or more numbered messages from the resolved hop names.

    Since MeshCore messages are limited to MAX_MSG_LENGTH characters, the
    hop list is split across multiple messages if necessary. The last entry
    before a split is replaced with "..." to indicate continuation.
    Follow-up messages begin with "(continued)".

    Args:
        sender_name: Name of the requesting node (used in the header)
        resolved:    List of resolved hop names from resolve_path()

    Returns:
        List of message strings (usually just one element).
    """
    numbered = [f"{i+1}. {n}" for i, n in enumerate(resolved)]

    messages = []
    header = f"Path @[{sender_name}]:\n"
    current = header

    i = 0
    while i < len(numbered):
        line = numbered[i] + "\n"

        if len(current) + len(line) <= MAX_MSG_LENGTH:
            current += line
            i += 1
        else:
            # Replace last hop of current message with "..." to signal continuation
            lines = current.rstrip("\n").split("\n")
            if len(lines) > 1:
                lines[-1] = "..."
                current = "\n".join(lines) + "\n"
            messages.append(current.rstrip("\n"))
            current = "(continued)\n"

    if current.strip():
        messages.append(current.rstrip("\n"))

    return messages


def get_rf_data(sender_timestamp: int) -> tuple[int | None, float | None, int | None]:
    """
    Reads RSSI, SNR, and reception timestamp of the most recently received
    message from a sender out of the RemoteTerm database.

    RemoteTerm stores RF metrics in the JSON field 'paths' of the 'messages'
    table. The lookup is done via sender_timestamp since the bot kwargs do
    not contain a direct message ID.

    Args:
        sender_timestamp: Unix timestamp of the sender (from bot kwargs)

    Returns:
        Tuple (rssi, snr, received_at) – values are None if not available.
        rssi:        Received signal strength in dBm (e.g. -87)
        snr:         Signal-to-noise ratio in dB (e.g. 6.5)
        received_at: Unix timestamp of reception by the companion node
    """
    if not sender_timestamp:
        return None, None, None
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute(
                "SELECT paths, received_at FROM messages "
                "WHERE sender_timestamp = ? AND outgoing = 0 "
                "ORDER BY id DESC LIMIT 1",
                (sender_timestamp,)
            )
            row = cur.fetchone()
            if row and row[0]:
                paths = json.loads(row[0])
                received_at = row[1]
                if paths:
                    rssi = paths[0].get("rssi")
                    snr = paths[0].get("snr")
                    return rssi, snr, received_at
    except Exception:
        pass
    return None, None, None


def get_path_hex_segments(path: str, bytes_per_hop: int) -> list[str]:
    """
    Splits the raw hex path into individual hop segments.

    Segment length depends on bytes_per_hop:
        1-byte → 2 hex characters per segment
        2-byte → 4 hex characters per segment
        3-byte → 6 hex characters per segment

    Args:
        path:          Raw hex path string
        bytes_per_hop: Bytes per hop

    Returns:
        List of hex segments (e.g. ["3a71", "6263", "4a0c"])
    """
    if not path or not bytes_per_hop:
        return []
    hex_per_hop = bytes_per_hop * 2
    return [path[i:i+hex_per_hop] for i in range(0, len(path), hex_per_hop)]


# ──────────────────────────────────────────────
# Bot entry point
# ──────────────────────────────────────────────

def bot(**kwargs) -> str | list[str] | None:
    """
    Main function of the RemoteTerm bot. Called by RemoteTerm for every
    incoming message.

    Supported keywords (case-insensitive, must be sent as standalone command):
        ping  → Replies with "Pong! @[Name] | N Hops"
        test  → Replies with hop count and raw path segments (if <= MAX_HOPS_DETAIL hops),
                or hop count and byte mode only (if > MAX_HOPS_DETAIL hops)
        path  → Replies with resolved hop names (may be split across messages)

    Keywords embedded in sentences are ignored (e.g. "Path @[C3PO]: ..." will
    not trigger the path handler). Optional ! or / prefix is supported (e.g. "!ping").

    Safety mechanisms:
        - is_outgoing guard: no response to own outgoing messages
        - is_keyword guard: only exact keyword matches trigger a response
        - MAX_HOPS limit: no response to nodes that are too far away
        - Channel filter: only configured channels are served

    Returns:
        None        → no reply
        str         → single reply message
        list[str]   → multiple messages (e.g. for long paths)
    """
    sender_name        = kwargs.get("sender_name")
    message_text       = kwargs.get("message_text", "")
    channel_name       = kwargs.get("channel_name")
    is_outgoing        = kwargs.get("is_outgoing", False)
    path               = kwargs.get("path")
    path_bytes_per_hop = kwargs.get("path_bytes_per_hop")
    sender_timestamp   = kwargs.get("sender_timestamp")

    # Ignore own outgoing messages
    if is_outgoing:
        return None

    msg = message_text.strip().lower()

    # Only respond in configured channels
    if channel_name not in CHANNEL_CONFIG:
        return None

    allowed_keywords = CHANNEL_CONFIG[channel_name]

    # Calculate hop count from path string
    if not path:
        hops = 0
    elif path_bytes_per_hop:
        hops = len(path) // (path_bytes_per_hop * 2)
    else:
        hops = 0

    # Ignore nodes that are too far away
    if hops > MAX_HOPS:
        return None

    name      = f"@[{sender_name}]" if sender_name else "unknown"
    hop_label = f"{hops} Hop" if hops == 1 else f"{hops} Hops"

    # ── ping ──────────────────────────────────
    if is_keyword(msg, "ping") and (allowed_keywords is None or "ping" in allowed_keywords):
        return f"Pong! {name} | {hop_label}"

    # ── test ──────────────────────────────────
    if is_keyword(msg, "test") and (allowed_keywords is None or "test" in allowed_keywords):
        if hops == 0:
            return f"ACK {name} | direct"

        if hops <= MAX_HOPS_DETAIL and path and path_bytes_per_hop:
            segments = get_path_hex_segments(path, path_bytes_per_hop)
            path_str = ",".join(segments)
            return f"ACK {name} | {hop_label} | {path_str} | {path_bytes_per_hop}-byte"
        else:
            return f"ACK {name} | {hop_label} | {path_bytes_per_hop}-byte"

    # ── path ──────────────────────────────────
    if is_keyword(msg, "path") and (allowed_keywords is None or "path" in allowed_keywords):
        if path:
            resolved = resolve_path(path, path_bytes_per_hop or 2)
            return build_path_messages(sender_name or "unknown", resolved)
        else:
            return f"Path {name} | direct (no relay)"

    return None
