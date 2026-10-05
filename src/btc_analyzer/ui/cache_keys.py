"""Exact content keys for public market frames, without repeated pandas row hashing."""

import hashlib
import pickle

import pandas as pd


def market_frame_key(frame: pd.DataFrame) -> str:
    """Hash complete values, shape, dtypes, labels and calculation metadata.

    Columns retain their own dtype, so large integers are never rounded through
    a mixed float matrix. Object/extension values use a lossless pickle fallback.
    No row sampling, object identity, mtime or latest-price-only shortcuts.
    """
    digest = hashlib.sha256()
    metadata = (
        frame.shape,
        tuple(frame.columns),
        tuple(map(str, frame.dtypes)),
        frame.index.name,
        str(frame.index.dtype),
        {key: value for key, value in frame.attrs.items() if key != "cached"},
    )
    digest.update(pickle.dumps(metadata, protocol=5))
    if isinstance(frame.index, pd.DatetimeIndex):
        digest.update(frame.index.as_unit("ns").asi8.tobytes())
    else:
        digest.update(pickle.dumps(frame.index, protocol=5))
    for _, column in frame.items():
        if isinstance(column.dtype, pd.api.extensions.ExtensionDtype):
            # Nullable Int64 with NA otherwise converts to float64 and loses
            # low bits above 2**53. Preserve its actual values and validity mask.
            payload = pickle.dumps(column.array, protocol=5)
        else:
            values = column.to_numpy(copy=False)
            payload = (
                pickle.dumps(values, protocol=5) if values.dtype.hasobject else values.tobytes(order="C")
            )
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)
    return digest.hexdigest()


MARKET_HASH_FUNCS = {pd.DataFrame: market_frame_key}
