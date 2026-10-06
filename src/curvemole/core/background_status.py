"""Associate background history with its spectrum's current model functions."""


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


def copy_background_history(source_curve, source, target_curve, previous, clone):
    """Copy functions without copying another spectrum's subtraction status."""
    clone.metadata.pop("background_subtraction_ids", None)
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
