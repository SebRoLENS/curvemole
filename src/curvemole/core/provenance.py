"""Immutable fit inputs, execution identity and checked computational replay."""
from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import marshal
import os
import platform
import sys
from functools import lru_cache
from pathlib import Path
from types import BuiltinFunctionType, CodeType, FunctionType, ModuleType

import numpy as np


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@lru_cache(maxsize=1)
def _software_identity():
    import scipy

    from curvemole.version import __version__
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    paths = sorted(root.rglob('*.py'))
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    if not paths:  # Frozen desktop builds retain the executable identity instead.
        with open(sys.executable, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
    return {'curvemole': __version__, 'python': platform.python_version(),
            'numpy': np.__version__, 'scipy': scipy.__version__,
            'source_sha256': digest.hexdigest(), 'platform': platform.platform(),
            'machine': platform.machine(),
            'numpy_build': copy.deepcopy(getattr(np.__config__, 'CONFIG', {}))}


def environment_record():
    importlib.import_module("scipy.linalg")
    importlib.import_module("scipy.optimize")
    record = copy.deepcopy(_software_identity())
    record['thread_environment'] = {key: os.environ.get(key) for key in (
        'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
        'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS')}
    try:
        from threadpoolctl import threadpool_info
        record['threadpools'] = threadpool_info()
        for pool in record['threadpools']:
            pool.pop('filepath', None)
    except ImportError:
        record['threadpools'] = None
    record['rng'] = {'resampling': np.random.PCG64.__name__,
                     'differential_evolution_seed': 'RandomState(MT19937)'}
    return record


def _without_source_path(code):
    return code.replace(
        co_filename="",
        co_consts=tuple(_without_source_path(item) if isinstance(item, CodeType) else item
                        for item in code.co_consts),
    )


def _evaluation_state(value, stack):
    """Encode callable inputs without reprs that hide mutable state or embed addresses."""
    from curvemole.core.expressions import SafeExpression

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return _evaluation_state(value.item(), stack)
    if isinstance(value, np.ndarray) and not value.dtype.hasobject:
        return {"array": [value.dtype.str, value.shape, hashlib.sha256(value.tobytes()).hexdigest()]}
    if isinstance(value, SafeExpression):
        return {"expression": value.source}
    if isinstance(value, ModuleType):
        # Arbitrary external namespaces can depend on mutable plugin state or
        # input files. Library identity is already captured by the environment.
        if value.__name__.split(".", 1)[0] not in {"math", "numpy", "scipy"}:
            raise TypeError(f"Module state of {value.__name__} cannot be verified.")
        return {"module": value.__name__, "version": getattr(value, "__version__", None)}
    if isinstance(value, (BuiltinFunctionType, np.ufunc)):
        return {"builtin": [getattr(value, "__module__", None), value.__name__]}
    identity = id(value)
    if identity in stack:
        raise TypeError("Recursive evaluator state cannot be verified.")
    child_stack = stack | {identity}
    if isinstance(value, (tuple, list)):
        return {type(value).__name__: [_evaluation_state(item, child_stack) for item in value]}
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _evaluation_state(item, child_stack) for key, item in value.items()}
    if isinstance(value, FunctionType):
        closure = inspect.getclosurevars(value)
        return {
            "code": hashlib.sha256(marshal.dumps(_without_source_path(value.__code__))).hexdigest(),
            "globals": _evaluation_state(closure.globals, child_stack),
            "nonlocals": _evaluation_state(closure.nonlocals, child_stack),
            "defaults": _evaluation_state(value.__defaults__, child_stack),
            "keyword_defaults": _evaluation_state(value.__kwdefaults__, child_stack),
        }
    raise TypeError(f"Evaluator state of type {type(value).__name__} cannot be verified.")


def function_records(registry, models):
    records = {}
    for model in models.values():
        for component in model.components:
            definition = registry.get(component.function_id)
            evaluator = definition.evaluator
            code = getattr(evaluator, '__code__', None)
            # Source paths are environment details, not function semantics.
            code_digest = None
            if code is not None:
                code_digest = hashlib.sha256(marshal.dumps(code.replace(co_filename=''))).hexdigest()
            value = {'identifier': definition.identifier,
                     'metadata': copy.deepcopy(definition.custom_metadata),
                     'evaluator_module': getattr(evaluator, '__module__', None),
                     'evaluator_code_sha256': code_digest}
            value['legacy_sha256'] = _digest(value)
            try:
                value['evaluation_state'] = _evaluation_state(evaluator, set())
                value['verifiable'] = True
            except (TypeError, ValueError):
                value['verifiable'] = False
            value['sha256'] = _digest(value)
            records[component.function_id] = value
    return records


def fit_record(plan, curves, models, registry):
    from dataclasses import asdict, fields

    from curvemole.core.extensions import current_extensions
    extensions = current_extensions()
    solver = next((entry for entry in extensions.values('fit_solvers')
                   if entry.identifier == plan.settings.solver), None)
    selected = {cid: models[cid] for cid in plan.curve_ids if cid in models}
    return {'schema_version': 2, 'kind': 'fit',
            'function_identity_version': 2,
            'plan': {'curve_ids': list(plan.curve_ids), 'mode': plan.mode.value,
                     'settings': asdict(plan.settings),
                     'spectrum_weights': dict(plan.spectrum_weights),
                     'equal_contribution': plan.equal_contribution},
            'sequential_options': {f.name: copy.deepcopy(getattr(plan, f.name)) for f in fields(plan)
                                   if f.name not in {'curve_ids', 'mode', 'settings',
                                                     'spectrum_weights', 'equal_contribution'}},
            'input_hashes': {curve.id: curve.content_hash for curve in curves},
            'initial_models': {cid: copy.deepcopy(model.to_dict()) for cid, model in selected.items()},
            'functions': function_records(registry, selected),
            'solver_extension': None if solver is None else {
                'identifier': solver.identifier, 'owner': solver.owner,
                'source_sha256': solver.source_sha256},
            'environment': environment_record()}


def select_fit_record(record, curve_id):
    if record.get('kind') != 'fit' or record.get('plan', {}).get('mode') == 'global':
        return copy.deepcopy(record)
    result = copy.deepcopy({key: value for key, value in record.items()
                            if key not in {'initial_models', 'input_hashes', 'executions'}})
    result['plan']['curve_ids'] = [curve_id]
    result['plan']['mode'] = 'independent'
    result['plan']['spectrum_weights'] = {
        curve_id: record['plan'].get('spectrum_weights', {}).get(curve_id, 1.0)}
    initial = record['initial_models'].get(curve_id)
    if record['plan']['mode'] == 'sequential':
        execution = next((item for item in record.get('executions', [])
                          if curve_id in item.get('initial_models', {})), None)
        if execution:
            initial = execution['initial_models'][curve_id]
    result['initial_models'] = {curve_id: copy.deepcopy(initial)}
    identifiers = {component['function_id'] for component in initial['components']} if initial else set()
    result['functions'] = {key: value for key, value in result['functions'].items() if key in identifiers}
    result['sequential_options'] = {}
    result['input_hashes'] = {curve_id: record['input_hashes'][curve_id]}
    result['executions'] = copy.deepcopy([value for value in record.get('executions', [])
                                         if curve_id in value.get('curve_ids', [])])
    return result


def analysis_record(method, baseline, plan, curves, models, registry, **configuration):
    record = fit_record(plan, [curves[cid] for cid in plan.curve_ids], models, registry)
    record['kind'] = method
    record['configuration'] = copy.deepcopy(configuration)
    record['baseline'] = {'timestamp': baseline.timestamp,
                          'parameters': {path: estimate.value for path, estimate in baseline.parameters.items()},
                          'provenance_sha256': _digest(baseline.provenance)}
    return record
