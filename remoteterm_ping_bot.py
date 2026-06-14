import sqlite3
import json
import re
from datetime import datetime, timezone

DB_PATH = "/opt/Remote-Terminal-for-MeshCore/data/meshcore.db"
MAX_HOPS = 10
MAX_MSG_LENGTH = 220

def resolve_path(path_hex: str, bytes_per_hop: int) -> list[str]:
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
                cur.execute("SELECT name FROM contacts WHERE public_key LIKE ? LIMIT 1", (hop + "%",))
                row = cur.fetchone()
                names.append(row[0] if row else f"[{hop}]")
            return names
    except Exception:
        return ["[path unavailable]"]

def build_path_messages(name: str, resolved: list[str]) -> list[str]:
    """
    Baut eine oder mehrere Nachrichten aus den aufgelösten Hop-Namen.
    Hops werden nummeriert. Bei Überschreitung von MAX_MSG_LENGTH wird
    die Nachricht gesplittet; der letzte Hop vor dem Split erhält '...'
    als Hinweis auf Fortsetzung.
    """
    numbered = [f"{i+1}. {name}" for i, name in enumerate(resolved)]
    messages = []
    header = f"Path @[{name}]:\n"
    current = header
    i = 0
    while i < len(numbered):
        line = numbered[i] + "\n"
        if len(current) + len(line) <= MAX_MSG_LENGTH:
            current += line
            i += 1
        else:
            lines = current.rstrip("\n").split("\n")
            if len(lines) > 1:
                lines[-1] = "..."
                current = "\n".join(lines) + "\n"
            messages.append(current.rstrip("\n"))
            current = f"(Fortsetzung)\n"
    if current.strip():
        messages.append(current.rstrip("\n"))
    return messages

def get_rf_data(sender_timestamp: int) -> tuple[int | None, float | None, int | None]:
    """Gibt (rssi, snr, received_at) zurück."""
    if not sender_timestamp:
        return None, None, None
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute(
                "SELECT paths, received_at FROM messages WHERE sender_timestamp = ? AND outgoing = 0 ORDER BY id DESC LIMIT 1",
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

def bot(**kwargs) -> str | list[str] | None:
    sender_name = kwargs.get("sender_name")
    message_text = kwargs.get("message_text", "")
    channel_name = kwargs.get("channel_name")
    is_outgoing = kwargs.get("is_outgoing", False)
    path = kwargs.get("path")
    path_bytes_per_hop = kwargs.get("path_bytes_per_hop")
    sender_timestamp = kwargs.get("sender_timestamp")

    if is_outgoing:
        return None

    # Eigene Bot-Antworten ignorieren (Schutz gegen Endlosschleife)
    msg = message_text.strip().lower()
    BOT_PREFIXES = ("pong!", "ack ", "path ", "(fortsetzung)")
    if any(msg.startswith(p) for p in BOT_PREFIXES):
        return None

    # Channel-Konfiguration: Channel → erlaubte Keywords (None = alle)
    CHANNEL_CONFIG = {
        "#ping":     {"ping"},
        "#test":     {"test"},
    }
    if channel_name not in CHANNEL_CONFIG:
        return None

    allowed_keywords = CHANNEL_CONFIG[channel_name]

    # Hop-Anzahl berechnen
    if not path:
        hops = 0
    elif path_bytes_per_hop:
        hops = len(path) // (path_bytes_per_hop * 2)
    else:
        hops = 0

    if hops > MAX_HOPS:
        return None

    name = f"@[{sender_name}]" if sender_name else "unknown"
    hop_label = f"{hops} Hop" if hops == 1 else f"{hops} Hops"

    if "ping" in msg and (allowed_keywords is None or "ping" in allowed_keywords):
        return f"Pong! {name} | {hop_label}"

    if "test" in msg and (allowed_keywords is None or "test" in allowed_keywords):
        rssi, snr, received_at = get_rf_data(sender_timestamp)
        # Pfad als kommagetrennte Kurzform
        if path and path_bytes_per_hop:
            hex_per_hop = path_bytes_per_hop * 2
            hop_hashes = [path[i:i+hex_per_hop] for i in range(0, len(path), hex_per_hop)]
            path_str = ",".join(hop_hashes) + f" ({hop_label})"
        elif hops == 0:
            path_str = f"direct ({hop_label})"
        else:
            path_str = hop_label
        rf = ""
        if snr is not None:
            rf += f" | SNR: {snr} dB"
        if rssi is not None:
            rf += f" | RSSI: {rssi} dBm"
        time_str = ""
        if received_at:
            try:
                dt = datetime.fromtimestamp(received_at, tz=timezone.utc).strftime("%H:%M:%S")
                time_str = f" | Received at: {dt}"
            except Exception:
                pass
        return f"ACK {name} | {path_str}{rf}{time_str}"

    if "path" in msg and (allowed_keywords is None or "path" in allowed_keywords):
        if path:
            resolved = resolve_path(path, path_bytes_per_hop or 2)
            return build_path_messages(sender_name or "unknown", resolved)
        else:
            return f"Path {name} | direct (no relay)"

    return None
