from __future__ import annotations

import textwrap
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch anchor not found:\n{old[:240]}")
    return text.replace(old, new, 1)


def class_block(source: str) -> str:
    return textwrap.indent(textwrap.dedent(source).lstrip("\n"), "    ")


def patch_plot() -> None:
    path = Path("src/curvemole/gui/plot.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from curvemole.gui.colours import MODEL_SUM_COLOUR\n",
        textwrap.dedent(
            """
            from curvemole.gui.plot_appearance import (
                colour_with_opacity,
                marker_for_curve,
                normalize_plot_appearance,
                plot_mode_flags,
                qt_pen_style,
            )
            """
        ).lstrip("\n"),
    )
    text = replace_once(
        text,
        '        self._placement_name = ""\n',
        '        self._placement_name = ""\n'
        "        self._plot_appearance = normalize_plot_appearance(None)\n",
    )
    text = replace_once(
        text,
        "        view_layout.addLayout(autoscale_controls)\n"
        "        offset_controls = QHBoxLayout()\n",
        textwrap.dedent(
            """
                    view_layout.addLayout(autoscale_controls)

                    function_controls = QHBoxLayout()
                    function_controls.setContentsMargins(0, 0, 0, 0)
                    function_controls.addWidget(QLabel(self.tr("Functions:")))
                    self.function_style_mode = QComboBox()
                    self.function_style_mode.addItem(self.tr("Lines"), "lines")
                    self.function_style_mode.addItem(self.tr("Points"), "points")
                    self.function_style_mode.addItem(
                        self.tr("Lines + points"), "lines_points"
                    )
                    self.function_style_mode.setToolTip(
                        self.tr("Choose how fitted/model functions are drawn in the plot.")
                    )
                    self.function_style_mode.currentIndexChanged.connect(
                        self._function_style_changed
                    )
                    function_controls.addWidget(self.function_style_mode)
                    function_controls.addStretch(1)
                    view_layout.addLayout(function_controls)

                    offset_controls = QHBoxLayout()
            """
        ).lstrip("\n"),
    )

    methods = class_block(
        """
        def plot_appearance(self) -> dict[str, Any]:
            return dict(self._plot_appearance)

        def set_plot_appearance(self, settings: dict[str, Any]) -> None:
            self._plot_appearance = normalize_plot_appearance(settings)
            if self._project is not None:
                self._project.ui_state["plot_appearance"] = dict(self._plot_appearance)
            self._sync_function_style_control()
            self._apply_grid_appearance()
            self.refresh()

        def _sync_function_style_control(self) -> None:
            value = str(self._plot_appearance.get("function_style", "lines"))
            index = self.function_style_mode.findData(value)
            self.function_style_mode.blockSignals(True)
            self.function_style_mode.setCurrentIndex(index if index >= 0 else 0)
            self.function_style_mode.blockSignals(False)

        def _function_style_changed(self, *_: Any) -> None:
            value = self.function_style_mode.currentData()
            if value is None:
                return
            self._plot_appearance["function_style"] = str(value)
            self._plot_appearance = normalize_plot_appearance(self._plot_appearance)
            if self._project is not None:
                self._project.ui_state["plot_appearance"] = dict(self._plot_appearance)
            self.refresh()

        def _apply_grid_appearance(self) -> None:
            visible = bool(self._plot_appearance.get("grid_visible", True))
            alpha = float(self._plot_appearance.get("grid_opacity", 15)) / 100.0
            self.plot.showGrid(x=visible, y=visible, alpha=alpha)
            self.residual_plot.showGrid(x=visible, y=visible, alpha=alpha)

        @staticmethod
        def _plot_options(
            mode: str,
            colour: str | QColor,
            width: float,
            line_style: str,
            opacity: int,
            point_size: float,
            symbol: str,
        ) -> dict[str, Any]:
            draw_lines, draw_points = plot_mode_flags(mode)
            rendered_colour = colour_with_opacity(colour, opacity)
            options: dict[str, Any] = {
                "pen": (
                    pg.mkPen(
                        rendered_colour,
                        width=width,
                        style=qt_pen_style(line_style),
                    )
                    if draw_lines
                    else None
                )
            }
            if draw_points:
                options.update(
                    symbol=symbol,
                    symbolSize=point_size,
                    symbolBrush=pg.mkBrush(rendered_colour),
                    symbolPen=None,
                )
            return options

        """
    )
    text = replace_once(text, "    def set_context(\n", methods + "    def set_context(\n")
    load_anchor = (
        "                self.autoscale_mode.setEnabled(self.autoscale_toggle.isChecked())\n"
        "                self.autoscale_mode.blockSignals(False)\n"
        "                self.autoscale_toggle.blockSignals(False)\n"
    )
    text = replace_once(
        text,
        load_anchor,
        load_anchor
        + "                self._plot_appearance = normalize_plot_appearance(\n"
        + '                    project.ui_state.get("plot_appearance")\n'
        + "                )\n"
        + "                self._sync_function_style_control()\n"
        + "                self._apply_grid_appearance()\n",
    )

    start = text.index("    def refresh(self, *_: Any) -> None:\n")
    end = text.index("    def set_component_labels_visible", start)
    refresh = class_block(
        """
        def refresh(self, *_: Any) -> None:
            initial_view = not self._data_items
            self.plot.clear()
            self.residual_plot.clear()
            self._data_items.clear()
            self._component_items.clear()
            self._component_labels.clear()
            self._component_label_specs.clear()
            self._handles.clear()
            self._placement_items.clear()
            project = self._project
            if project is None or not project.curves:
                self.plot.setTitle(self.tr("Import data to begin"))
                return
            appearance = self._plot_appearance
            mode = self.display_mode.currentText()
            curves = self.displayed_curves()
            x_step = self.x_offset.value() if mode == self.tr("Waterfall") else 0.0
            y_step = self.y_offset.value() if mode == self.tr("Waterfall") else 0.0
            global_values = project.resolved_parameter_values()
            for index, curve in enumerate(curves):
                x = curve.x + index * x_step
                y = curve.y + index * y_step
                unmasked = ~curve.effective_mask
                symbol = marker_for_curve(appearance, index)
                data_width = float(appearance["data_line_width"]) * (
                    1.35 if curve.id == self._active_curve_id else 1.0
                )
                item = self.plot.plot(
                    x[unmasked],
                    y[unmasked],
                    name=curve.name,
                    **self._plot_options(
                        str(appearance["data_style"]),
                        curve.colour,
                        data_width,
                        str(appearance["data_line_style"]),
                        int(appearance["data_opacity"]),
                        float(appearance["data_point_size"]),
                        symbol,
                    ),
                )
                item.curve_id = curve.id
                self._data_items[curve.id] = item
                for mask in curve.masks.values():
                    for lower, upper in mask.ranges:
                        if math.isclose(lower, upper):
                            continue
                        region = pg.LinearRegionItem(
                            values=(lower + index * x_step, upper + index * x_step),
                            movable=False,
                            brush=pg.mkBrush(120, 120, 120, 38),
                            pen=pg.mkPen(120, 120, 120, 70),
                        )
                        region.setZValue(-20)
                        self.plot.addItem(region)
                model = project.models.get(curve.id)
                if model and model.components:
                    try:
                        total, component_arrays = model.evaluate(
                            curve.x,
                            curve_id=curve.id,
                            values=global_values,
                            registry=self.registry,
                            components=True,
                        )
                    except CurveMoleError as exc:
                        self.plot.setToolTip(
                            f"Model unavailable: {exc}. Review File → Plugin Manager."
                        )
                        continue
                    total = total + index * y_step
                    sum_item = self.plot.plot(
                        x,
                        total,
                        name=f"{curve.name} Model sum",
                        **self._plot_options(
                            str(appearance["function_style"]),
                            str(appearance["model_sum_colour"]),
                            float(appearance["function_sum_line_width"]),
                            str(appearance["function_sum_line_style"]),
                            int(appearance["function_opacity"]),
                            float(appearance["function_point_size"]),
                            symbol,
                        ),
                    )
                    sum_item.curve_id = curve.id
                    residual = curve.y - (total - index * y_step)
                    self.residual_plot.plot(
                        x[unmasked],
                        residual[unmasked],
                        **self._plot_options(
                            str(appearance["residual_style"]),
                            curve.colour,
                            float(appearance["residual_line_width"]),
                            str(appearance["residual_line_style"]),
                            int(appearance["residual_opacity"]),
                            float(appearance["residual_point_size"]),
                            symbol,
                        ),
                    )
                    for component in model.components:
                        if not component.enabled or component.id not in component_arrays:
                            continue
                        component_y = component_arrays[component.id] + index * y_step
                        selected = (
                            component.id == self._selected_component_id
                            and curve.id == self._active_curve_id
                        )
                        colour = (
                            str(appearance["selected_component_colour"])
                            if selected
                            else str(appearance["component_colour"])
                        )
                        width = (
                            float(appearance["function_selected_line_width"])
                            if selected
                            else float(appearance["function_component_line_width"])
                        )
                        component_item = self.plot.plot(
                            x,
                            component_y,
                            **self._plot_options(
                                str(appearance["function_style"]),
                                colour,
                                width,
                                str(appearance["function_component_line_style"]),
                                int(appearance["function_opacity"]),
                                float(appearance["function_point_size"]),
                                symbol,
                            ),
                        )
                        component_item.component_id = component.id
                        component_item.curve_id = curve.id
                        component_item.curve.setClickable(
                            True,
                            width=max(
                                8.0,
                                float(appearance["function_point_size"]) + 4.0,
                            ),
                        )
                        component_item.sigClicked.connect(
                            lambda item, event, component_id=component.id: (
                                self.componentSelected.emit(component_id)
                            )
                        )
                        self._component_items[component.id] = component_item
                        if self._show_component_labels:
                            self._add_component_label(component.name, x, component_y)
                    if curve.id == self._active_curve_id and self._selected_component_id:
                        self._add_component_handles(
                            curve,
                            model,
                            index * x_step,
                            index * y_step,
                        )
            if curves:
                first = curves[0]
                self.plot.setLabel("bottom", first.x_label, units=first.x_unit or None)
                self.plot.setLabel("left", first.y_label, units=first.y_unit or None)
                self.residual_plot.setLabel(
                    "bottom",
                    first.x_label,
                    units=first.x_unit or None,
                )
            self._apply_grid_appearance()
            self._layout_component_labels()
            self._render_placement_preview()
            self.plot.setTitle("")
            if initial_view:
                self.auto_range()

        """
    )
    text = text[:start] + refresh + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_main_window() -> None:
    path = Path("src/curvemole/gui/main_window.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from curvemole.gui.plot import PlotWorkspace\n",
        "from curvemole.gui.plot import PlotWorkspace\n"
        "from curvemole.gui.plot_appearance import PlotAppearanceDialog\n",
    )
    action_anchor = (
        '        self.lock_view_action = QAction(self.tr("Lock plot view"), self, checkable=True)\n'
        "        self.lock_view_action.toggled.connect(self.plot_workspace.set_view_locked)\n"
    )
    text = replace_once(
        text,
        action_anchor,
        action_anchor
        + '        self.plot_appearance_action = QAction(self.tr("Plot appearance…"), self)\n'
        + "        self.plot_appearance_action.setToolTip(\n"
        + '            self.tr("Customize lines, points, symbols, colours, residuals and grid rendering.")\n'
        + "        )\n"
        + "        self.plot_appearance_action.triggered.connect(self.configure_plot_appearance)\n",
    )
    method = class_block(
        """
        def configure_plot_appearance(self) -> None:
            dialog = PlotAppearanceDialog(self.plot_workspace.plot_appearance(), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.plot_workspace.set_plot_appearance(dialog.settings())

        """
    )
    text = replace_once(text, "    def _build_menus(self) -> None:\n", method + "    def _build_menus(self) -> None:\n")
    menu_anchor = textwrap.dedent(
        """
                view_menu.addActions(
                    [
                        self.series_dock.toggleViewAction(),
                        self.model_dock.toggleViewAction(),
                        self.worksheet_action,
                        self.diagnostics_action,
                        self.log_action,
                    ]
                )
        """
    ).lstrip("\n")
    text = replace_once(
        text,
        menu_anchor,
        menu_anchor
        + "        view_menu.addSeparator()\n"
        + "        view_menu.addAction(self.plot_appearance_action)\n",
    )
    path.write_text(text, encoding="utf-8")


def patch_background_navigation() -> None:
    path = Path("src/curvemole/gui/background_navigation.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from curvemole.gui.plot import PlotWorkspace\n",
        "from curvemole.gui.plot import PlotWorkspace\n"
        + textwrap.dedent(
            """
            from curvemole.gui.plot_appearance import (
                colour_with_opacity,
                marker_for_curve,
                plot_mode_flags,
                qt_pen_style,
            )
            """
        ).lstrip("\n"),
    )
    start = text.index("def _masked_sample_renderer(workspace: PlotWorkspace) -> None:\n")
    end = text.index("\ndef _item_name", start)
    renderer = textwrap.dedent(
        """
        def _masked_sample_renderer(workspace: PlotWorkspace) -> None:
            """Render excluded samples using the current project appearance settings."""
            curves, x_step, y_step = _displayed_curves(workspace)
            if not curves:
                return
            subtract = bool(getattr(workspace, "_background_subtracted_view", False))
            cache = getattr(workspace, "_curvemole_background_cache", {})
            appearance = workspace.plot_appearance()
            draw_lines, draw_points = plot_mode_flags(str(appearance["data_style"]))

            for index, curve in enumerate(curves):
                x = np.asarray(curve.x, dtype=float) + index * x_step
                y = np.asarray(curve.y, dtype=float)
                if subtract:
                    y = y - np.asarray(cache.get(curve.id, np.zeros_like(y)), dtype=float)
                y = y + index * y_step
                masked = (
                    np.asarray(curve.effective_mask, dtype=bool)
                    & np.isfinite(x)
                    & np.isfinite(y)
                )
                if not np.any(masked):
                    continue
                colour = colour_with_opacity(
                    curve.colour,
                    int(appearance["masked_opacity"]),
                )
                line_pen = pg.mkPen(
                    colour,
                    width=float(appearance["data_line_width"]),
                    style=qt_pen_style(str(appearance["data_line_style"])),
                )
                symbol = marker_for_curve(appearance, index)

                if draw_lines:
                    isolated_x: list[float] = []
                    isolated_y: list[float] = []
                    for run in _mask_display._true_runs(masked):
                        if run.size == 1:
                            point = int(run[0])
                            isolated_x.append(float(x[point]))
                            isolated_y.append(float(y[point]))
                            continue
                        item = workspace.plot.plot(x[run], y[run], pen=line_pen)
                        item._curvemole_masked_data = True
                        item.curve_id = curve.id
                        item.setZValue(4.0)
                    if isolated_x and not draw_points:
                        item = workspace.plot.plot(
                            np.asarray(isolated_x, dtype=float),
                            np.asarray(isolated_y, dtype=float),
                            pen=None,
                            symbol=symbol,
                            symbolSize=float(appearance["masked_point_size"]),
                            symbolBrush=pg.mkBrush(colour),
                            symbolPen=None,
                        )
                        item._curvemole_masked_data = True
                        item.curve_id = curve.id
                        item.setZValue(4.0)

                if draw_points:
                    item = workspace.plot.plot(
                        x[masked],
                        y[masked],
                        pen=None,
                        symbol=symbol,
                        symbolSize=float(appearance["masked_point_size"]),
                        symbolBrush=pg.mkBrush(colour),
                        symbolPen=None,
                    )
                    item._curvemole_masked_data = True
                    item.curve_id = curve.id
                    item.setZValue(4.0)

        """
    ).lstrip("\n")
    text = text[:start] + renderer + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_docs() -> None:
    path = Path("docs/quick-start.md")
    text = path.read_text(encoding="utf-8")
    if "## Plot appearance" in text:
        return
    text += textwrap.dedent(
        """

        ## Plot appearance

        The view-controls panel includes **Functions: Lines / Points / Lines + points**
        for quick switching. For deeper customization use **View > Plot appearance…**.
        Appearance settings are stored with the project and include experimental-data
        style, line widths/styles, point size and symbols, optional per-spectrum symbol
        cycling, model/component colours and widths, residual rendering, masked-point
        appearance, and grid visibility/opacity.
        """
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_plot()
    patch_main_window()
    patch_background_navigation()
    patch_docs()
