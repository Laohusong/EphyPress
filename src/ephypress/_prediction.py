"""Descriptive prediction modes, with parameters taken from the compiled codec."""

PREDICTIONS = ("temporal", "spatiotemporal")


def prediction_parameters(prediction):
    if prediction not in PREDICTIONS:
        raise ValueError("prediction must be 'temporal' or 'spatiotemporal'")
    from . import _codec

    parameters = {
        "temporal_numerator": _codec.temporal_numerator,
        "temporal_denominator": _codec.temporal_denominator,
    }
    if prediction == "spatiotemporal":
        parameters.update(
            spatial_weights=list(_codec.spatial_weights), spatial_denominator=_codec.spatial_denominator
        )
    return parameters
