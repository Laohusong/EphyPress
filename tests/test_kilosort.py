import numpy as np
import pytest

pytest.importorskip("kilosort")
import torch
from kilosort.io import BinaryRWFile

from ephypress import compress, open_recording


def test_native_ks4_reads_cross_block_padding_and_variable_batches(tmp_path):
    data = np.random.default_rng(19).integers(-2000, 2000, (131071, 3), dtype=np.int16)
    raw, archive = tmp_path / "raw.dat", tmp_path / "test.ep"
    data.tofile(raw)
    compress(raw, archive, 3, block_samples=40003, workers=2)
    with open_recording(archive) as reader:
        for batch in (60000, 65536):
            args = dict(n_chan_bin=3, NT=batch, nt=61, device=torch.device("cpu"))
            original = BinaryRWFile(raw, **args)
            compressed = BinaryRWFile(archive, file_object=reader, **args)
            for index in range(int(original.n_batches)):
                assert torch.equal(
                    original.padded_batch_to_torch(index), compressed.padded_batch_to_torch(index)
                )


def test_public_ks4_helper_uses_packaged_rans_reader(tmp_path, monkeypatch):
    from ephypress import run_kilosort

    data = np.arange(3000, dtype="i2").reshape(1000, 3)
    raw, archive = tmp_path / "raw.dat", tmp_path / "test.ep"
    data.tofile(raw)
    compress(raw, archive, 3, block_samples=113)
    captured = []

    def run(**kwargs):
        reader = kwargs["file_object"]
        captured.append(reader)
        assert reader.metadata["entropy_backend"] == "rans"
        assert reader._prefetch_blocks == 32 and reader._cache_limit == 64
        assert kwargs["settings"]["n_chan_bin"] == 3
        assert kwargs["settings"]["fs"] == 30000
        assert kwargs["save_preprocessed_copy"] is False
        assert np.array_equal(reader[100:700], data[100:700])
        return "result"

    monkeypatch.setattr("kilosort.run_kilosort", run)
    assert run_kilosort(archive, results_dir=tmp_path / "sorting") == "result"
    assert captured[0]._closed
