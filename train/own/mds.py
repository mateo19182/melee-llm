"""Read the zstd shards of HAL's dataset (MosaicML Streaming format) without its library, which manages the folder
it is pointed at as a cache and deletes shards."""
import json
import os

import numpy as np

_SHAPE_BYTES = {0: 1, 1: 2, 2: 4, 3: 8}


def read_shard(path, columns):
    """Yield the rows of one zstd MDS shard, decoding only `columns`."""
    import zstandard
    idx = json.load(open(os.path.join(os.path.dirname(path), "index.json")))
    info = next(s for s in idx["shards"] if s["zip_data"]["basename"] == os.path.basename(path))
    names, encs, sizes = info["column_names"], info["column_encodings"], info["column_sizes"]
    with open(path, "rb") as fh:
        raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
    n = int(np.frombuffer(raw, np.uint32, 1)[0])
    offsets = np.frombuffer(raw, np.uint32, n + 1, 4)
    for i in range(n):
        data, pos = memoryview(raw)[offsets[i]:offsets[i + 1]], 0
        lens = []
        for size in sizes:
            if size is None:
                size = int(np.frombuffer(data, np.uint32, 1, pos)[0]); pos += 4
            lens.append(size)
        row = {}
        for name, enc, size in zip(names, encs, lens):
            if name in columns:
                row[name] = _decode(enc, data[pos:pos + size])
            pos += size
        yield row


def _decode(enc, b):
    if enc == "int":
        return int(np.frombuffer(b, np.int64)[0])
    if enc == "str":
        return bytes(b).decode()
    assert enc.startswith("ndarray:"), enc  # static dtype, shape stored in front
    ndim, width = b[0] >> 2, _SHAPE_BYTES[b[0] % 4]
    shape = np.frombuffer(b, f"u{width}", ndim, 1)
    return np.frombuffer(b, enc.split(":")[1], offset=1 + ndim * width).reshape(shape)
