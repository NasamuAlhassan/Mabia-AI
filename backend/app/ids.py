"""Time-sortable identifiers.

Events carry client-generated IDs so that a retry over a bad link is safe: the
server de-duplicates on the ID and a replayed request is a no-op. The IDs are
time-sortable (UUIDv7 layout) so that a replay in insertion order is also a
replay in chronological order, without trusting a device clock for ordering.
"""
import os
import time
import uuid


def uuid7() -> str:
    """A UUIDv7: 48 bits of millisecond timestamp, then randomness."""
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand = int.from_bytes(os.urandom(10), "big")
    # 48-bit timestamp | version 7 | 12 bits rand | variant | 62 bits rand
    value = ms << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & 0x3FFFFFFFFFFFFFFF
    return str(uuid.UUID(int=value))


def short_id() -> str:
    return uuid7().split("-")[0] + uuid7().split("-")[1]
