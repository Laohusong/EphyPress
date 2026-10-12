import numpy as np
import pytest

pytest.importorskip("kilosort")
import torch
from kilosort.io import BinaryRWFile

from ephypress import compress, open_recording


def test_native_ks4_reads_cross_block_padding_and_variable_batches(tmp_path):
    data = np.random.default_rng(19).integers(-2000, 2000, (131071, 3), dtype=np.int16)
    raw, archive = tmp_path / "raw.dat", tmp_path / "test.spc"
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
