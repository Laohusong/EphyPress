import numpy as np
import pytest

from ephypress import compress, decompress, info, open_recording, verify
from ephypress._container import PREFIX, write_blocks


def test_lossless_extrema_cross_block_windows_and_view_lifetime(tmp_path):
    data = np.random.default_rng(17).integers(-32768, 32768, (12319, 3), dtype=np.int16)
    data[0, :2] = [-32768, 32767]
    raw, archive, restored = [tmp_path / name for name in ("input.dat", "test.ep", "restored.bin")]
    data.tofile(raw)
    result = compress(
        raw,
        archive,
        3,
        sampling_frequency=20000,
        block_samples=4097,
        workers=2,
    )
    assert result["source_bytes"] == data.nbytes
    assert info(archive)["prediction"] == "delta"
    with open_recording(archive, prefetch_blocks=2) as reader:
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
    decompress(archive, restored)
    assert restored.read_bytes() == raw.read_bytes()
    with pytest.raises(FileExistsError):
        decompress(archive, restored)
    with pytest.raises(FileExistsError):
        compress(raw, archive, 3)


def test_corruption_and_unknown_formats_rejected(tmp_path):
    raw, archive = tmp_path / "raw.dat", tmp_path / "test.ep"
    np.arange(8000, dtype="<i2").tofile(raw)
    compress(raw, archive, 2, block_samples=512)
    contents = archive.read_bytes()
    damaged = bytearray(contents)
    damaged[PREFIX.size + 20] ^= 1
    bad = tmp_path / "payload.ep"
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
    with pytest.raises(ValueError, match="Unsupported"):
        info(bad)


def test_atomic_publication_never_overwrites_a_racing_destination(tmp_path):
    archive = tmp_path / "racing.ep"

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
        compress(raw, tmp_path / "test.ep", value)


def test_delta_wire_bytes_match_independent_numpy_reference():
    from ephypress._native import encode_channels16

    data = np.array([[32767, -32768, 0], [-32768, 32767, -1], [19, -20, 1]], dtype="<i2")
    expected = np.concatenate([data[:1], np.diff(data, axis=0)])
    assert encode_channels16(data).tobytes() == expected.tobytes(order="F")
