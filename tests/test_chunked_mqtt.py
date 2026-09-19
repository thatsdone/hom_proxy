#!/usr/bin/env python3
#
# test_chunked_mqtt.py: unit tests for device/chunked_mqtt.py and
# proxy/chunked_mqtt.py (issue #4: "Allow very large message transfer").
#
# These tests need no MQTT broker; they exercise split_message() and
# Reassembler purely in-process.
#
# Run with (from the repo root):
#   $ pip install -r requirements-test.txt
#   $ pytest tests/
#
# License:
#   Apache License, Version 2.0
import filecmp
import os
import random
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'device'))

from chunked_mqtt import (
    DEFAULT_MAX_CHUNK_SIZE,
    ChunkError,
    Reassembler,
    parse_chunk,
    split_message,
)


def reassemble_in_order(payload: bytes, max_chunk_size: int) -> bytes:
    """Reference reassembly: feed chunks to a fresh Reassembler in the
    order split_message() produced them."""
    r = Reassembler()
    result = None
    for chunk in split_message(payload, max_chunk_size):
        result = r.add_chunk(chunk)
    return result


# ---------------------------------------------------------------------
# device/ and proxy/ intentionally carry identical copies of this
# module (mirroring how the rest of the repo duplicates MQTT boilerplate
# between the two components rather than sharing a package). Guard
# against the two copies silently drifting apart.
# ---------------------------------------------------------------------
def test_device_and_proxy_copies_match():
    device_copy = os.path.join(REPO_ROOT, 'device', 'chunked_mqtt.py')
    proxy_copy = os.path.join(REPO_ROOT, 'proxy', 'chunked_mqtt.py')
    assert filecmp.cmp(device_copy, proxy_copy, shallow=False), (
        'device/chunked_mqtt.py and proxy/chunked_mqtt.py have diverged; '
        'keep them identical (or replace the duplication with a shared '
        'package as a follow-up).')


# ---------------------------------------------------------------------
# Round-trip correctness
# ---------------------------------------------------------------------
@pytest.mark.parametrize('size', [0, 1, 100, 4096, 500_000, 2_000_001])
@pytest.mark.parametrize('max_chunk_size', [64, 1024, 65536, DEFAULT_MAX_CHUNK_SIZE])
def test_round_trip(size, max_chunk_size):
    payload = os.urandom(size)
    assert reassemble_in_order(payload, max_chunk_size) == payload


def test_single_chunk_fast_path_does_not_buffer():
    payload = b'small message'
    r = Reassembler()
    chunks = split_message(payload, DEFAULT_MAX_CHUNK_SIZE)
    assert len(chunks) == 1
    result = r.add_chunk(chunks[0])
    assert result == payload
    assert r._pending == {}


def test_many_small_random_sizes():
    rng = random.Random(1234)
    for _ in range(50):
        size = rng.randint(0, 20_000)
        max_chunk_size = rng.randint(65, 4096)
        payload = os.urandom(size)
        assert reassemble_in_order(payload, max_chunk_size) == payload


# ---------------------------------------------------------------------
# Realistic MQTT delivery conditions: reordering and duplication.
# QoS 1 ("at least once") guarantees neither strict ordering (under
# retransmits with in-flight window > 1) nor exactly-once delivery.
# ---------------------------------------------------------------------
def test_out_of_order_chunks_reassemble_correctly():
    payload = os.urandom(50_000)
    chunks = split_message(payload, 1024)
    assert len(chunks) > 3  # otherwise this test isn't exercising much

    shuffled = chunks[:]
    rng = random.Random(42)
    rng.shuffle(shuffled)

    r = Reassembler()
    result = None
    for chunk in shuffled:
        result = r.add_chunk(chunk)
    assert result == payload


def test_duplicate_chunks_are_idempotent():
    payload = os.urandom(10_000)
    chunks = split_message(payload, 1024)

    r = Reassembler()
    result = None
    for chunk in chunks:
        r.add_chunk(chunk)
        result = r.add_chunk(chunk)  # redeliver the same chunk
    assert result == payload


def test_interleaved_messages_on_the_same_topic_do_not_cross_contaminate():
    payload_a = b'A' * 10_000
    payload_b = b'B' * 12_000
    chunks_a = split_message(payload_a, 1024)
    chunks_b = split_message(payload_b, 1024)

    r = Reassembler()
    result_a = result_b = None
    # interleave: a0 b0 a1 b1 a2 b2 ...
    for ca, cb in zip(chunks_a, chunks_b):
        ra = r.add_chunk(ca)
        rb = r.add_chunk(cb)
        result_a = result_a or ra
        result_b = result_b or rb
    # feed any remaining chunks (lists may differ in length)
    for ca in chunks_a[len(chunks_b):]:
        result_a = result_a or r.add_chunk(ca)
    for cb in chunks_b[len(chunks_a):]:
        result_b = result_b or r.add_chunk(cb)

    assert result_a == payload_a
    assert result_b == payload_b


# ---------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------
def test_dropped_chunk_never_completes():
    payload = os.urandom(10_000)
    chunks = split_message(payload, 1024)
    assert len(chunks) > 2

    r = Reassembler()
    result = None
    for chunk in chunks[:-1]:  # withhold the last chunk
        result = r.add_chunk(chunk)
    assert result is None


def test_corrupt_payload_is_detected_by_crc():
    payload = os.urandom(5000)
    chunks = split_message(payload, 1024)
    # flip a bit well inside the data portion of the first chunk
    header_len = len(chunks[0]) - len(parse_chunk(chunks[0])['data'])
    tampered = bytearray(chunks[0])
    tampered[header_len] ^= 0xFF
    chunks[0] = bytes(tampered)

    r = Reassembler()
    with pytest.raises(ChunkError):
        for chunk in chunks:
            r.add_chunk(chunk)


def test_too_short_chunk_is_rejected():
    r = Reassembler()
    with pytest.raises(ChunkError):
        r.add_chunk(b'\x00\x01\x02')


def test_bad_magic_is_rejected():
    payload = b'x' * 100
    chunk = split_message(payload, DEFAULT_MAX_CHUNK_SIZE)[0]
    tampered = b'XXXX' + chunk[4:]
    r = Reassembler()
    with pytest.raises(ChunkError):
        r.add_chunk(tampered)


def test_max_chunk_size_must_exceed_header():
    with pytest.raises(ValueError):
        split_message(b'x', max_chunk_size=4)


# ---------------------------------------------------------------------
# Bounded memory use
# ---------------------------------------------------------------------
def test_ttl_expiry_drops_abandoned_partial_message():
    payload = os.urandom(10_000)
    chunks = split_message(payload, 1024)
    assert len(chunks) > 2

    r = Reassembler(ttl_seconds=0.05)
    r.add_chunk(chunks[0])  # start a partial message, then abandon it

    import time
    time.sleep(0.1)

    # A subsequent, unrelated call triggers the sweep; the abandoned
    # message must not still be sitting in memory.
    other_payload = b'y' * 100
    r.add_chunk(split_message(other_payload, DEFAULT_MAX_CHUNK_SIZE)[0])
    assert len(r._pending) == 0


def test_max_pending_evicts_oldest():
    r = Reassembler(max_pending=2)
    payloads = [os.urandom(5000) for _ in range(3)]
    chunk_sets = [split_message(p, 1024) for p in payloads]

    # Start 3 partial messages (only send the first chunk of each), one
    # more than max_pending allows.
    for cs in chunk_sets:
        r.add_chunk(cs[0])

    assert len(r._pending) <= 2
