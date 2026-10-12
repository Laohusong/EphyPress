from pathlib import Path

import numpy as np
import pytest

from ephypress import compress, decompress, info, open_recording, verify
from ephypress._container import PREFIX, write_blocks
from ephypress._entropy import decode_bytes, encode_bytes


@pytest.mark.parametrize("backend", ["fse", "zstd"])
@pytest.mark.parametrize("profile", ["level1", "legacy"])
@pytest.mark.parametrize("mode", ["blocks", "auto"])
def test_lossless_extrema_cross_block_windows_and_view_lifetime(tmp_path, backend, profile, mode):
    data = np.random.default_rng(17).integers(-32768, 32768, (12319, 3), dtype=np.int16)
    data[0, :2] = [-32768, 32767]
    raw, archive, restored = [tmp_path / name for name in ("input.dat", "test.spc", "restored.bin")]
    data.tofile(raw)
    result = compress(
        raw,
        archive,
        3,
        sampling_frequency=20000,
        block_samples=4097,
        entropy_backend=backend,
        profile=profile,
        workers=2,
    )
    assert result["source_bytes"] == data.nbytes
    assert info(archive)["quantum"] == 1
    with open_recording(archive, reader_mode=mode, prefetch_blocks=2) as reader:
        old = reader[4000:8300]
        assert np.array_equal(old, data[4000:8300])
        assert np.array_equal(reader[::-97, [2, 0]], data[::-97, [2, 0]])
        assert np.array_equal(reader[[-1, 0, 4111], 1], data[[-1, 0, 4111], 1])
        assert np.array_equal(reader[np.int64(-1)], data[-1])
        assert reader[12:12].shape == (0, 3)
        assert np.array_equal(reader[0:6000], data[0:6000])
        assert np.array_equal(old, data[4000:8300])
        tail = reader.read_batch(12000, 1000, halo=(20, 30), pad="edge")
        expected = np.pad(data[11980:], [(0, 1270), (0, 0)], mode="edge")[:1050]
        assert np.array_equal(tail, expected)
        assert not old.flags.writeable
        stats = reader.statistics()
        assert not stats["raw_disk_cache"] and stats["max_pending_blocks"] <= 2
    assert np.array_equal(old, data[4000:8300])
    assert verify(archive, original=raw)["max_abs_error"] == 0
    decompress(archive, restored, reader_mode=mode)
    assert restored.read_bytes() == raw.read_bytes()
    with pytest.raises(FileExistsError):
        decompress(archive, restored)
    with pytest.raises(FileExistsError):
        compress(raw, archive, 3)


@pytest.mark.parametrize(
    "values",
    [
        np.zeros(7, dtype="u1"),
        np.arange(256, dtype="u1"),
        np.random.default_rng(7).integers(0, 9, 60000, dtype="u1"),
    ],
)
def test_bundled_fse_raw_rle_and_compressed_packets(values):
    assert np.array_equal(decode_bytes(encode_bytes(values), len(values)), values)
    with pytest.raises(ValueError):
        decode_bytes(b"", len(values))


def test_corruption_and_lossy_archives_rejected(tmp_path):
    raw, archive = tmp_path / "raw.dat", tmp_path / "test.spc"
    np.arange(8000, dtype="<i2").tofile(raw)
    compress(raw, archive, 2, block_samples=512)
    contents = archive.read_bytes()
    damaged = bytearray(contents)
    damaged[PREFIX.size + 20] ^= 1
    bad = tmp_path / "payload.spc"
    bad.write_bytes(damaged)
    with pytest.raises(ValueError, match="checksum"):
        verify(bad)
    bad.write_bytes(contents[:-1])
    with pytest.raises(ValueError):
        info(bad)
    damaged = bytearray(contents)
    damaged[-1] ^= 1
    bad.write_bytes(damaged)
    with pytest.raises(ValueError, match="index checksum"):
        info(bad)
    damaged = bytearray(contents)
    damaged[:8] = b"SPKC04\x00\x00"
    bad.write_bytes(damaged)
    with pytest.raises(ValueError, match="lossless"):
        info(bad)


def test_atomic_publication_never_overwrites_a_racing_destination(tmp_path):
    archive = tmp_path / "racing.spc"

    def source(a, b):
        archive.write_bytes(b"existing data")
        return np.zeros((b - a, 1), dtype="<i2")

    with pytest.raises(FileExistsError):
        write_blocks(source, archive, (100, 1), block_samples=100, workers=1)
    assert archive.read_bytes() == b"existing data"
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("value", [0, True, 1.5])
def test_invalid_dimensions(tmp_path, value):
    raw = tmp_path / "raw.dat"
    raw.write_bytes(b"\0\0")
    with pytest.raises(ValueError):
        compress(raw, tmp_path / "test.spc", value)


@pytest.mark.parametrize("name", ["level1_p53", "legacy_p41"])
def test_legacy_research_archive_compatibility(name):
    path = Path(__file__).parent / "fixtures" / f"{name}.spc"
    data = ((np.arange(777 * 3, dtype=np.int64) * 37) % 65536 - 32768).astype("<i2").reshape(777, 3)
    with open_recording(path) as reader:
        assert np.array_equal(reader[:], data)
    assert verify(path)["exact_equal"]
