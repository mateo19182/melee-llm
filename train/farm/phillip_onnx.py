"""Rewrite a published Phillip ONNX export (fixed batch of 1) to take any batch size.

    uv run --no-project --with onnx --with numpy python farm/phillip_onnx.py SRC.onnx DST.onnx

The exporter baked the batch of 1 into the graph in two places:
- Reshape targets built from constants start with 1. Each such Reshape gets its own copy of the shape with -1 there.
  (The constants are shared between nodes, so they are copied rather than edited.) Targets that already start with
  -1 are left alone; any other Reshape stops the conversion.
- One Squeeze of the batch axis turns the packed temperature into a scalar; the graph uses the first entry anyway
  (onnx_policies.OnnxAgent packs the same value for every row), so it becomes Gather(index 0).
Inputs and outputs get a symbolic batch dimension. farm/phillip.py checks the result row for row against the original.
"""
import sys

import numpy as np
import onnx
from onnx import helper, numpy_helper


def batchify(src, dst):
    model = onnx.load(src)
    g = model.graph
    for vi in list(g.input) + list(g.output):
        d = vi.type.tensor_type.shape.dim[0]
        d.ClearField("dim_value")
        d.dim_param = "batch"
    del g.value_info[:]
    inits = {i.name: i for i in g.initializer}
    producers = {o: n for n in g.node for o in n.output}

    def constant(name):
        if name in inits:
            return numpy_helper.to_array(inits[name])
        n = producers.get(name)
        if n is None:
            return None
        if n.op_type == "Constant":
            return numpy_helper.to_array(n.attribute[0].t)
        if n.op_type == "Concat":
            parts = [constant(i) for i in n.input]
            return None if any(p is None for p in parts) else np.concatenate(parts)
        return None

    reshapes = squeezes = 0
    for k, n in enumerate(g.node):
        if n.op_type == "Reshape":
            shape = constant(n.input[1])
            if shape is not None and len(shape) and shape[0] == -1:
                continue  # already batch-generic
            if shape is None or len(shape) == 0 or shape[0] != 1 or -1 in shape:
                raise ValueError(f"{n.name}: target shape {shape} is not a constant starting with the batch")
            shape = shape.astype(np.int64).copy()
            shape[0] = -1
            g.initializer.append(numpy_helper.from_array(shape, f"batched_shape_{k}"))
            n.input[1] = f"batched_shape_{k}"
            reshapes += 1
        elif n.op_type == "Squeeze" and len(n.input) > 1 and constant(n.input[1]) is not None \
                and constant(n.input[1]).tolist() == [0]:
            g.initializer.append(numpy_helper.from_array(np.array(0, np.int64), f"first_row_{k}"))
            n.op_type, n.input[1] = "Gather", f"first_row_{k}"
            del n.attribute[:]
            n.attribute.append(helper.make_attribute("axis", 0))
            squeezes += 1
    if squeezes != 1:
        raise ValueError(f"expected one batch-axis Squeeze (the temperature), found {squeezes}")
    onnx.save(model, dst)
    print(f"{src}: {reshapes} reshapes, {squeezes} squeeze rewritten", file=sys.stderr)


if __name__ == "__main__":
    batchify(sys.argv[1], sys.argv[2])
