#!/usr/bin/env python3
#
# chunked_mqtt.py: split/reassemble MQTT payloads that exceed the
# broker's configured message size limit.
#
# MQTT's own protocol ceiling is 256MB (the 4-byte variable-length
# Remaining Length encoding), but brokers almost always configure a
# much lower limit (e.g. NanoMQ/EMQX commonly default to 1MB). This
# module lets a payload of any size be published as a sequence of
# smaller sub-messages on the same topic, and reassembled on the
# receiving side.
#
# Every outgoing payload, including ones that fit in a single chunk,
# is wrapped in the same small header. This keeps the receiver to a
# single code path instead of having to special-case "chunked" vs.
# "plain" messages.
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/09/19 v0.1 Initial version
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
# TODO:
#   * many
import logging
import struct
import time
import uuid
import zlib

logger = logging.getLogger(__name__)

# magic(4s) + version(B) + message_id(16s) + seq(I) + total(I)
# + total_len(Q) + crc32(I)
_MAGIC = b'HOMC'
_VERSION = 1
_HEADER_FMT = '!4sB16sIIQI'
_HEADER_LEN = struct.calcsize(_HEADER_FMT)

# Default max size, in bytes, of a single MQTT publish payload
# (envelope header + chunk data). Keep this comfortably under the
# broker's configured message size limit -- do not rely on MQTT's
# 256MB protocol ceiling, most brokers configure far less.
DEFAULT_MAX_CHUNK_SIZE = 256 * 1024


class ChunkError(Exception):
    """Raised for a malformed, corrupt, or out-of-protocol chunk envelope."""


def split_message(payload: bytes, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE) -> list[bytes]:
    """Wrap `payload` into one or more chunk envelopes, each no larger
    than `max_chunk_size` bytes (including the envelope header).

    Always returns at least one chunk, even for an empty payload, so
    the caller has one code path regardless of message size. Caller is
    expected to mqtt.publish() each returned chunk, in order, to the
    same topic.
    """
    if max_chunk_size <= _HEADER_LEN:
        raise ValueError(
            f'max_chunk_size ({max_chunk_size}) must be greater than '
            f'the envelope header size ({_HEADER_LEN})')

    data_size = max_chunk_size - _HEADER_LEN
    total_len = len(payload)
    message_id = uuid.uuid4().bytes
    crc = zlib.crc32(payload) & 0xffffffff

    # ceil(total_len / data_size), minimum of 1 chunk (covers the
    # empty-payload case too).
    total = max(1, -(-total_len // data_size))

    chunks = []
    for seq in range(total):
        start = seq * data_size
        chunk_data = payload[start:start + data_size]
        header = struct.pack(_HEADER_FMT, _MAGIC, _VERSION, message_id,
                              seq, total, total_len, crc)
        chunks.append(header + chunk_data)
    return chunks


def parse_chunk(raw: bytes) -> dict:
    """Parse a single chunk envelope into its header fields plus data."""
    if len(raw) < _HEADER_LEN:
        raise ChunkError(f'chunk too short: {len(raw)} bytes')
    magic, version, message_id, seq, total, total_len, crc = struct.unpack(
        _HEADER_FMT, raw[:_HEADER_LEN])
    if magic != _MAGIC:
        raise ChunkError(f'bad magic: {magic!r}')
    if version != _VERSION:
        raise ChunkError(f'unsupported chunk envelope version: {version}')
    if total < 1 or seq >= total:
        raise ChunkError(f'seq {seq} out of range for total {total}')
    return {
        'message_id': message_id,
        'seq': seq,
        'total': total,
        'total_len': total_len,
        'crc32': crc,
        'data': raw[_HEADER_LEN:],
    }


class Reassembler:
    """Buffers chunks per message_id and returns the full payload once
    every chunk of a message has arrived.

    Bounded so a sender that dies mid-transfer, or a burst of partial
    messages, cannot grow memory without limit:
      * max_pending: max number of in-flight (incomplete) messages.
      * max_total_bytes: max bytes buffered across all pending messages.
      * ttl_seconds: how long an incomplete message is kept before
        being dropped as abandoned.
    When a bound is hit, the oldest pending message is dropped to make
    room; a sender whose message gets dropped this way will simply
    time out waiting for a reply, same as any other delivery failure.
    """

    def __init__(self, max_pending: int = 64,
                 max_total_bytes: int = 64 * 1024 * 1024,
                 ttl_seconds: float = 120.0):
        self._pending: dict[bytes, dict] = {}
        # Small cache of message_id -> (completed_at, payload) for
        # messages that have already been fully reassembled and
        # returned. Under QoS 1 ("at least once"), a chunk can be
        # redelivered after its message was already completed; without
        # this, that duplicate would start a bogus new partial
        # reassembly that then just sits until it expires. Bounded by
        # max_pending entries (not by max_total_bytes -- a burst of
        # large completed messages can therefore transiently use more
        # memory than max_total_bytes alone implies).
        self._completed: dict[bytes, tuple[float, bytes]] = {}
        self.max_pending = max_pending
        self.max_total_bytes = max_total_bytes
        self.ttl_seconds = ttl_seconds

    def add_chunk(self, raw: bytes) -> bytes | None:
        """Feed one raw MQTT payload (a chunk envelope) in. Returns the
        fully reassembled payload once complete, else None.
        """
        self._expire()
        chunk = parse_chunk(raw)

        if chunk['total'] == 1:
            # Fast path: unfragmented message, nothing to buffer.
            data = chunk['data']
            self._verify(data, chunk)
            return data

        message_id = chunk['message_id']

        cached = self._completed.get(message_id)
        if cached is not None:
            # Redelivery of a chunk from a message we already finished
            # reassembling; hand back the same result again instead of
            # treating it as the start of a new message.
            return cached[1]

        entry = self._pending.get(message_id)
        if entry is None:
            self._make_room()
            entry = {
                'total': chunk['total'],
                'total_len': chunk['total_len'],
                'crc32': chunk['crc32'],
                'chunks': {},
                'created': time.monotonic(),
            }
            self._pending[message_id] = entry

        if chunk['total'] != entry['total'] or chunk['total_len'] != entry['total_len']:
            raise ChunkError(f'inconsistent envelope for message {message_id.hex()}')

        # Indexed by seq (not appended), so duplicate/retransmitted or
        # out-of-order chunks -- both expected under QoS 1 -- are
        # handled without extra bookkeeping.
        entry['chunks'][chunk['seq']] = chunk['data']

        if len(entry['chunks']) < entry['total']:
            self._enforce_byte_budget()
            return None

        data = b''.join(entry['chunks'][i] for i in range(entry['total']))
        del self._pending[message_id]
        self._verify(data, entry)
        self._remember_completed(message_id, data)
        return data

    def _total_buffered(self) -> int:
        return sum(len(c) for m in self._pending.values() for c in m['chunks'].values())

    def _remember_completed(self, message_id: bytes, data: bytes):
        if len(self._completed) >= self.max_pending:
            oldest_id = min(self._completed, key=lambda mid: self._completed[mid][0])
            del self._completed[oldest_id]
        self._completed[message_id] = (time.monotonic(), data)

    def _expire(self):
        now = time.monotonic()
        expired = [mid for mid, m in self._pending.items()
                   if now - m['created'] > self.ttl_seconds]
        for mid in expired:
            m = self._pending.pop(mid)
            logger.warning(
                'Dropping expired partial message %s (%d/%d chunks received)',
                mid.hex(), len(m['chunks']), m['total'])

        expired_completed = [mid for mid, (ts, _) in self._completed.items()
                             if now - ts > self.ttl_seconds]
        for mid in expired_completed:
            del self._completed[mid]

    def _make_room(self):
        if len(self._pending) < self.max_pending:
            return
        oldest_id = min(self._pending, key=lambda mid: self._pending[mid]['created'])
        logger.warning('Too many in-flight partial messages (%d), dropping oldest %s',
                        self.max_pending, oldest_id.hex())
        del self._pending[oldest_id]

    def _enforce_byte_budget(self):
        while self._pending and self._total_buffered() > self.max_total_bytes:
            oldest_id = min(self._pending, key=lambda mid: self._pending[mid]['created'])
            logger.warning(
                'Buffered chunk data exceeds %d bytes, dropping oldest partial message %s',
                self.max_total_bytes, oldest_id.hex())
            del self._pending[oldest_id]

    @staticmethod
    def _verify(data: bytes, meta: dict):
        if len(data) != meta['total_len']:
            raise ChunkError(
                f"length mismatch: reassembled {len(data)} bytes, "
                f"expected {meta['total_len']}")
        crc = zlib.crc32(data) & 0xffffffff
        if crc != meta['crc32']:
            raise ChunkError(f"CRC mismatch: got {crc:#010x}, expected {meta['crc32']:#010x}")
