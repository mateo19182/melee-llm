"""Training HAL's released 247M model on one 24 GB GPU (docs/experiments/E19-hal-train-loop.md).

Run with HAL's own environment, from train/:

    ../vendor/hal/.venv/bin/python -m haltrain.validate

Nothing of HAL's is copied here. The model, optimiser and loaders come from vendor/hal/hal; the loss, the return
labels and the validation metric come from HAL's training script, experiments/059_muon_action_sequence.py, made
importable by o59.py.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HAL = REPO / "vendor/hal"
WEIGHTS = HAL / "weights/hal-250m.hal"
DATA = Path("/mnt/data/melee/hal-mds")   # HAL's public dataset (ericyuegu/hal-mds-dataset), same folder layout
AMSA = 568                               # player id of AMSA#0 in the released vocabulary


def o59():
    """HAL's training script as a module (see o59.py)."""
    import importlib
    return importlib.import_module("haltrain.o59")


def load_model(path=WEIGHTS, device="cuda"):
    """The released weights as a full-precision, trainable model, with the artifact (stats, vocabulary, return p90)."""
    import torch
    from hal.inference.action_sequence_artifact import read_action_sequence_artifact
    from hal.models.action_sequence import ActionSequenceTransformer

    artifact = read_action_sequence_artifact(path)
    with torch.device("meta"):
        model = ActionSequenceTransformer(artifact.model_config, artifact.vocabulary)
    model.load_state_dict(artifact.model_tensors, strict=True, assign=True)
    return model.to(device), artifact


def take(batch, index):
    """The rows of a ReturnBatch picked by `index` (a slice or an index tensor), without replay ids."""
    from hal.representation.features import Context
    from hal.training.batches import TrainBatch

    return type(batch)(
        TrainBatch(Context({k: v[index] for k, v in batch.context.features.items()}, batch.context.ctx_pad[index]),
                   batch.target[index], None),
        batch.returns[index], batch.eligible[index], batch.future_return[index], batch.available[index],
        batch.condition_present[index])


def save_bundle(model, source, destination, name):
    """Write `model`'s weights as a bundle like `source` (same statistics, vocabulary and return calibration)."""
    import hashlib
    import json
    import tempfile

    import torch
    from hal.inference import action_sequence_artifact as art

    with art.extract_policy_bundle(source) as (manifest, root), tempfile.TemporaryDirectory() as tmp:
        raw = torch.load(root / art._CHECKPOINT_MEMBER, map_location="cpu", weights_only=False)
        raw["model"] = {k: v.detach().float().cpu() for k, v in model.state_dict().items()}
        checkpoint = Path(tmp) / art._CHECKPOINT_MEMBER
        torch.save(raw, checkpoint)
        config = json.loads((root / art._CONFIG_MEMBER).read_text())
        config["checkpoint_sha256"] = art.checkpoint_sha256(checkpoint)
        config_path = Path(tmp) / art._CONFIG_MEMBER
        config_path.write_text(json.dumps(config, sort_keys=True, separators=(",", ":")))
        art.write_policy_bundle(
            destination,
            art.BundleDescription(
                policy_name=name, backend=manifest.backend, backend_version=manifest.backend_version,
                required_observation_fields=manifest.required_observation_fields,
                supported_transport_delays=manifest.supported_transport_delays,
                requires_player_code=manifest.requires_player_code, source_sha256=config["checkpoint_sha256"]),
            {art._CONFIG_MEMBER: config_path, art._STATS_MEMBER: root / art._STATS_MEMBER,
             art._CHECKPOINT_MEMBER: checkpoint})
