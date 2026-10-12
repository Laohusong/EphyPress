from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from ephypress import compress, decompress, open_recording, verify
from ephypress._io import PositionedFile


def test_seek_read_fallback_is_safe_under_concurrent_prefetch(tmp_path):
    content = np.arange(100000, dtype="<i2").tobytes()
    source = tmp_path / "电生理 recording.dat"
    source.write_bytes(content)
    positioned = PositionedFile(source)
    positioned._pread = None
    cases = [(offset, 1001) for offset in range(0, len(content) - 1001, 997)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda case: positioned.read_at(case[1], case[0]), cases))
        assert all(
            value == content[offset : offset + length] for value, (offset, length) in zip(results, cases)
        )
    finally:
        positioned.close()
    with pytest.raises(ValueError, match="closed"):
        positioned.read_at(1, 0)


def test_default_reader_unicode_paths_and_binary_control_bytes(tmp_path):
    # Line endings and Ctrl-Z must remain bytes on native Windows.
    source, archive, restored = [
        tmp_path / name for name in ("原始 数据.dat", "压缩 recording.spc", "还原 data.dat")
    ]
    data = np.resize(np.array([10, 13, 26, -32768, 32767, -1], dtype="<i2"), (13001, 3))
    data.tofile(source)
    compress(source, archive, 3, block_samples=4097, workers=4)
    with open_recording(archive) as reader:
        assert np.array_equal(reader[4000:11000], data[4000:11000])
    assert verify(archive, original=source)["exact_equal"]
    decompress(archive, restored)
    assert restored.read_bytes() == source.read_bytes()


def test_writer_refuses_float_blocks_even_if_source_metadata_is_incorrect(tmp_path):
    from ephypress._container import write_blocks

    with pytest.raises(ValueError, match="int16"):
        write_blocks(
            lambda first, last: np.zeros((last - first, 1), dtype="f4"), tmp_path / "test.spc", (10, 1)
        )
