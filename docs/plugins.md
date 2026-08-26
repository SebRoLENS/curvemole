# CurveMole plugin guide

Built-ins and extensions share `FunctionDefinition` and `FunctionRegistry`.
Publicly distributed plugins must provide source under a GPL-compatible licence.

Local plugins use a manifest that can be inspected without executing Python:

```json
{
  "identifier": "org.example.my-lineshape",
  "version": "1.0.0",
  "api_compatibility": "1",
  "licence": "GPL-3.0-or-later",
  "capabilities": ["functions"],
  "module": "my_lineshape.py"
}
```

The Python module exposes one function:

```python
from curvemole.core.functions import FunctionDefinition, ParameterSpec

def evaluate(x, p, metadata):
    return p["scale"] * x

def register(registry):
    registry.register(FunctionDefinition(
        "org.example.linear_scale",
        "Example scale",
        "generic",
        evaluate,
        (ParameterSpec("scale", 1.0),),
    ))
```

Place both files in a plugin directory. CurveMole reads the JSON first and executes
the `.py` file only after an explicit trust decision. Unattended workflows require
the matching `--trust-plugin` identifier.

Installed packages may expose the `curvemole.functions` Python entry-point group.
Entry points are likewise never loaded before trust is explicit.
