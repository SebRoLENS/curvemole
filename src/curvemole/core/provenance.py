"""Immutable fit inputs, execution identity and checked computational replay."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import platform
import sys
from functools import lru_cache
from pathlib import Path

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
                import marshal
                code_digest = hashlib.sha256(marshal.dumps(code.replace(co_filename=''))).hexdigest()
            value = {'identifier': definition.identifier,
                     'metadata': copy.deepcopy(definition.custom_metadata),
                     'evaluator_module': getattr(evaluator, '__module__', None),
                     'evaluator_code_sha256': code_digest}
            value['sha256'] = _digest(value)
            records[component.function_id] = value
    return records


def fit_record(plan, curves, models, registry):
    from dataclasses import asdict, fields

    from curvemole.core.extensions import extensions
    solver = next((entry for entry in extensions.values('fit_solvers')
                   if entry.identifier == plan.settings.solver), None)
    selected = {cid: models[cid] for cid in plan.curve_ids if cid in models}
    return {'schema_version': 1, 'kind': 'fit',
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
