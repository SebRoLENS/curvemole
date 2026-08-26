# Python API

```python
import numpy as np
from curvemole import Curve, Component, FitSettings, Fitter, Model

x = np.linspace(-5, 5, 1001)
y = ...
curve = Curve("IR band", x, y)

model = Model("One band")
model.add(Component.create("constant", initial={"offset": 0.0}))
model.add(Component.create("gaussian", initial={"area": 10, "center": 0, "sigma": 1}))

result = Fitter().fit_single(curve, model, FitSettings(loss="linear"))
print(result.statistics)
```

For a cross-spectrum link, construct the full path and use `${...}`:

```python
source_path = model_a.parameter_path(curve_a.id, component_a.id, "center")
component_b.parameters["center"].link = "${" + source_path + "}"
```

The public package root exposes `Dataset`, `Series`, `Curve`, `Model`, `Component`,
`Parameter`, `FitPlan`, `FitResult`, `Fitter`, `FunctionRegistry`, and `Project`.
Core modules never import GUI modules.
