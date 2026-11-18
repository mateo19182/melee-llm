"""The farm's batched Faynt cache gives the same outputs as Faynt's own per-row cache.

Runs in the Faynt venv with a GPU and the released weights:
    cd train && PYTHONPATH=.:<repo> ../vendor/Faynt-Tournament/.venv/bin/python -m pytest tests/test_faynt_farm.py
"""
import dataclasses

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
from faynt import farm  # noqa: E402

pytestmark = pytest.mark.skipif(not (torch.cuda.is_available() and (farm.WEIGHTS / "Faynt-10M-Arena").exists()),
                                reason="needs a GPU and the Faynt weights")


def _frames(model, batch, n, seed=0):
    """n step inputs: the model's neutral fixture with positions, actions and the stick moving per row and frame."""
    g = torch.Generator().manual_seed(seed)
    base = model.example_inputs(batch, None, device="cuda")
    for _ in range(n):
        state, controller = base["game_state_t"], base["controller_t"]
        p0 = dataclasses.replace(state.p0, x=(torch.rand(batch, generator=g) * 120 - 60).cuda(),
                                 action=torch.randint(0, 340, (batch,), generator=g).cuda())
        stick = dataclasses.replace(controller.main_stick, x=torch.rand(batch, generator=g).cuda())
        yield dataclasses.replace(state, p0=p0), dataclasses.replace(controller, main_stick=stick)


def test_batched_cache_matches_upstream():
    from transformers import AutoModel

    model = AutoModel.from_pretrained(str(farm.WEIGHTS / "Faynt-10M-Arena"), trust_remote_code=True).eval().cuda()
    cls = type(model.policy.backbone.layers[0].attention)
    original = cls.forward_cached
    batch, n = 5, 300  # past the 256-frame ring, so it wraps
    resets = {(40, 1), (40, 3), (290, 0)}  # (frame, row): new games mid-run

    def run():
        cache, out = model.init_cache(batch, device="cuda"), []
        with torch.inference_mode():
            for t, (state, controller) in enumerate(_frames(model, batch, n)):
                reset = torch.tensor([t == 0 or (t, r) in resets for r in range(batch)], device="cuda")
                o = model.step(game_state_t=state, controller_t=controller, cache=cache, reset_mask=reset,
                               sample=False)
                out.append(torch.cat([o.logits["buttons"].float(), o.logits["main_stick"].float()], -1))
        return torch.stack(out)

    try:
        cls.forward_cached, cls._batched = original, False
        upstream = run()
        farm.batched_cache(model)
        ours = run()
    finally:
        cls.forward_cached, cls._batched = original, False
    assert ours.shape == upstream.shape
    diff = (ours - upstream).abs().max().item()
    print("max logit diff", diff)
    assert diff < 0.05, diff
    agree = (ours[..., :728].argmax(-1) == upstream[..., :728].argmax(-1)).float().mean().item()
    print("argmax agreement", agree)
    assert agree > 0.99, agree


def test_graph_step_matches_eager():
    """The recorded CUDA graph computes what the eager batched step computes, frame after frame. Button logits are
    compared: they depend only on the history, while the stick's depend on the sampled buttons."""
    from transformers import AutoModel

    model = AutoModel.from_pretrained(str(farm.WEIGHTS / "Faynt-10M-Arena"), trust_remote_code=True).eval().cuda()
    batch, n = 5, 300
    resets = {(40, 1), (40, 3), (290, 0)}
    graph = farm.GraphStep(model, batch, temperature=1.0)
    cache, worst = model.init_cache(batch, device="cuda"), 0.0
    for t, (state, controller) in enumerate(_frames(model, batch, n)):
        reset = [t == 0 or (t, r) in resets for r in range(batch)]
        for (_, ours), (_, theirs) in zip(graph.inputs, farm._leaves(state)):
            ours.copy_(theirs)
        graph.step(reset)
        with torch.inference_mode():
            eager = model.step(game_state_t=state, controller_t=state.p0.controller, cache=cache,
                               reset_mask=torch.tensor(reset, device="cuda"), sample=False)
        worst = max(worst, (graph.button_logits.float() - eager.logits["buttons"].float()).abs().max().item())
    print("max button logit diff", worst)
    assert worst < 0.05, worst
