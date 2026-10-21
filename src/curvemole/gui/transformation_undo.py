"""Replay a native transformation after a plugin recreates project objects."""

from __future__ import annotations

import copy

from curvemole.core.data import Curve, Transformation


def same_transformation(left: Transformation, right: Transformation) -> bool:
    """Match the persisted operation identity without comparing numeric arrays."""
    return left.created_at == right.created_at and left.operation == right.operation


def redo_transformation(curve: Curve, transformation: Transformation) -> None:
    if curve.redo_transformations and same_transformation(curve.redo_transformations[-1], transformation):
        curve.redo_transformation()
    elif not any(same_transformation(item, transformation) for item in curve.transformations):
        curve.apply_transformation(copy.deepcopy(transformation))


def undo_transformation(curve: Curve, transformation: Transformation) -> None:
    if curve.transformations and same_transformation(curve.transformations[-1], transformation):
        curve.undo_transformation()
