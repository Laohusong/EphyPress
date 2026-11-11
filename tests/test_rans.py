"""Lossless, compatibility and ownership checks for the production rANS path."""

import base64
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from ephypress import decompress, info, open_recording, verify
from ephypress._container import MAGIC, PREFIX, write_blocks
from ephypress._rans import Decoder, encode


@pytest.mark.parametrize("shape", [(1, 1), (1, 7), (7, 1), (65, 33), (4097, 3)])
@pytest.mark.parametrize("distribution", ["zeros", "extrema", "noise", "small_delta"])
def test_rans_modular_delta_roundtrip_and_tail(tmp_path, shape, distribution):
    rng = np.random.default_rng(91)
    data = rng.integers(-32768, 32768, shape, dtype=np.int16)
    if distribution == "zeros":
        data[:] = 0
    elif distribution == "extrema":
        data[:] = np.resize(np.array([-32768, 32767, -1, 0], dtype="i2"), shape)
    elif distribution == "small_delta":
        data = np.cumsum(rng.integers(-3, 4, shape), axis=0).astype("<i2")
    archive, restored = tmp_path / "test.ep", tmp_path / "restored.dat"
    write_blocks(lambda a, b: data[a:b], archive, shape, block_samples=101, workers=2)
    assert info(archive)["entropy_backend"] == "rans"
    assert info(archive)["format_version"] == 3
    with open_recording(archive, prefetch_blocks=3, cache_blocks=4) as reader:
        assert np.array_equal(reader[:], data)
        held = reader[: min(100, len(data))]
        expected = held.copy()
        assert np.array_equal(reader[::-2, ::-1], data[::-2, ::-1])
        assert np.array_equal(reader[-1], data[-1])
        assert np.array_equal(held, expected)
        assert not held.flags.writeable
        cores = list(reader.iter_cores())
    assert np.array_equal(np.concatenate(cores), data)
    assert np.array_equal(held, expected)
    assert verify(archive)["exact_equal"]
    decompress(archive, restored)
    assert restored.read_bytes() == data.tobytes()


def test_recycling_under_jumps_preserves_held_windows_and_cores(tmp_path):
    data = np.random.default_rng(12).integers(-32768, 32768, (10003, 5), dtype="i2")
    path = tmp_path / "recording.ep"
    write_blocks(lambda a, b: data[a:b], path, data.shape, block_samples=113)
    with open_recording(path, cache_blocks=4, prefetch_blocks=3) as reader:
        held = reader[77:200]
        for start in [5000, 0, 9000, 113, 2000, 100, 8000, 3000, 7000, 4000]:
            assert np.array_equal(reader[start : start + 199], data[start : start + 199])
        cores = list(reader.iter_cores())
        assert np.array_equal(np.concatenate(cores), data)
        assert np.array_equal(held, data[77:200])
        stats = reader.statistics()
        assert stats["output_buffer_reuses"] > 0
        assert stats["worker_contexts"] <= 3
        assert len(reader._online_frames) <= 4
        assert stats["max_decoded_cache_bytes"] <= 4 * 113 * 5 * 2
    reader.close()
    assert not reader._decoders
    assert np.array_equal(held, data[77:200])


@pytest.mark.parametrize("fault", ["model", "sum", "state", "truncated", "trailing", "escapes"])
def test_invalid_rans_packets_are_rejected_without_crc(tmp_path, fault):
    data = np.arange(101 * 3, dtype="i2").reshape(101, 3)
    packet = bytearray(encode(data))
    if fault == "model":
        struct.pack_into("<I", packet, 0, 2)
    elif fault == "sum":
        struct.pack_into("<H", packet, 8, 65535)
    elif fault == "state":
        struct.pack_into("<I", packet, 2058, 0)
    elif fault == "truncated":
        packet = packet[:2073]
    elif fault == "trailing":
        packet += b"extra"
    elif fault == "escapes":
        struct.pack_into("<I", packet, 4, 1)
    path = tmp_path / "packet.dat"
    path.write_bytes(packet)
    decoder = Decoder(path)
    try:
        with pytest.raises(ValueError):
            decoder.decode(0, len(packet), 0, data.shape, False)
    finally:
        decoder.close()


def test_golden_payload_and_v3_encoder_match(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/rans_delta.json").read_text())
    data = np.array(fixture["data"], dtype="<i2")
    assert encode(data) == base64.b64decode(fixture["payload"])
    path = tmp_path / "recording.ep"
    write_blocks(lambda a, b: data[a:b], path, data.shape)
    assert path.read_bytes()[:8] == MAGIC
    with open_recording(path) as reader:
        assert np.array_equal(reader[:], data)
        assert reader._prefetch_blocks == 32 and reader._cache_limit == 64


@pytest.mark.parametrize("version", [1, 2, 4])
def test_unsupported_container_versions_are_rejected(tmp_path, version):
    path = tmp_path / "recording.ep"
    data = np.arange(100, dtype="<i2").reshape(50, 2)
    write_blocks(lambda a, b: data[a:b], path, data.shape)
    contents = path.read_bytes()
    magic, offset, length = PREFIX.unpack_from(contents)
    metadata = json.loads(contents[offset : offset + length])
    metadata["format_version"] = version
    index = json.dumps(metadata).encode()
    path.write_bytes(
        PREFIX.pack(magic, offset, len(index))
        + contents[PREFIX.size : offset]
        + index
        + hashlib.sha256(index).digest()
    )
    with pytest.raises(ValueError, match="version"):
        info(path)
