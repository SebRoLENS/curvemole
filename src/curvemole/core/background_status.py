"""Associate background history with its spectrum's current model functions."""

import re

from curvemole.core.registry import default_registry


def _name_key(name):
    return re.sub(r"[\W_]+", "", name).casefold()


def _legacy_function(name, registry):
    matches = [definition.identifier for definition in registry.values()
               if re.fullmatch(re.escape(_name_key(definition.display_name)) + r"\d*", _name_key(name))]
    return matches[0] if len(matches) == 1 else None


def _references(transformation):
    if transformation.operation != "background_subtract":
        return
    names = transformation.parameters.get("component_names", [])
    functions = transformation.parameters.get("component_functions", {})
    for index, identity in enumerate(transformation.parameters.get("component_ids", [])):
        name = names[index] if index < len(names) else ""
        yield identity, name, functions.get(identity)


def restore_background_history(project, registry=None):
    """Reconnect old renamed/copied builtin backgrounds without altering the data/model."""
    registry = registry or default_registry()
    for curve in project.curves:
        model = project.models.get(curve.id)
        if model is None:
            continue
        owned = set().union(*(background_component_ids(c) for c in model.components))
        for transformation in (*curve.transformations, *curve.redo_transformations):
            # New records distinguish replacements from the original functions.
            # Inference is reserved for legacy files without that provenance.
            if "component_functions" in transformation.parameters:
                continue
            for identity, name, _function in _references(transformation):
                if identity in owned or not name:
                    continue
                function = _legacy_function(name, registry)
                if function is None:
                    continue
                candidates = [c for c in model.components if c.is_background
                              and c.function_id == function
                              and not c.metadata.get("background_history_detached")
                              and identity not in c.metadata.get("background_unresolved_ids", [])]
                named = [c for c in candidates if _name_key(c.name) == _name_key(name)]
                if named:
                    candidates = named
                else:
                    # Old automatic names can have been renumbered on reopening.
                    candidates = [c for c in candidates
                                  if not c.metadata.get("custom_name")
                                  and _legacy_function(c.name, registry) == function]
                if len(candidates) != 1:
                    for component in candidates:
                        unresolved = set(component.metadata.get("background_unresolved_ids", [])) | {identity}
                        component.metadata["background_unresolved_ids"] = sorted(unresolved)
                    continue
                component = candidates[0]
                aliases = background_component_ids(component) | {identity}
                aliases.discard(component.id)
                component.metadata["background_subtraction_ids"] = sorted(aliases)
                owned.add(identity)


def background_component_ids(component):
    if isinstance(component, str):
        return {component}
    previous = component.metadata.get("background_subtraction_ids", [])
    return {component.id, *(value for value in previous if isinstance(value, str))}


def background_component_subtracted(curve, component):
    identities = background_component_ids(component)
    return any(transformation.operation == "background_subtract"
               and identities.intersection(transformation.parameters.get("component_ids", ()))
               for transformation in curve.transformations)


def background_component_status(curve, component, model, registry=None):
    if background_component_subtracted(curve, component):
        return "subtracted"
    if component.metadata.get("background_history_detached"):
        return "not_subtracted"
    registry = registry or default_registry()
    owned = set().union(*(background_component_ids(c) for c in model.components))
    for transformation in curve.transformations:
        for identity, name, function in _references(transformation):
            if identity in owned:
                continue
            function = function or _legacy_function(name, registry)
            if function is None or function == component.function_id:
                return "unresolved"
    return "not_subtracted"


def copy_background_history(source_curve, source, target_curve, previous, clone):
    """Copy functions without copying another spectrum's subtraction status."""
    clone.metadata.pop("background_subtraction_ids", None)
    clone.metadata.pop("background_history_detached", None)
    clone.metadata.pop("background_unresolved_ids", None)
    if previous is not None and previous.metadata.get("background_unresolved_ids"):
        clone.metadata["background_unresolved_ids"] = list(previous.metadata["background_unresolved_ids"])
    if previous is None or previous.metadata.get("background_history_detached"):
        clone.metadata["background_history_detached"] = True
    if previous is not None:
        used = {component_id for transformation in (*target_curve.transformations, *target_curve.redo_transformations)
                if transformation.operation == "background_subtract"
                for component_id in transformation.parameters.get("component_ids", ())}
        history = background_component_ids(previous).intersection(used)
        if history:
            clone.metadata["background_subtraction_ids"] = sorted(history)
    if clone.is_background:
        target_subtracted = previous is not None and background_component_subtracted(target_curve, previous)
        source_subtracted = background_component_subtracted(source_curve, source)
        if target_subtracted or (source_subtracted and not source.enabled):
            clone.enabled = previous.enabled if previous is not None else not target_subtracted
