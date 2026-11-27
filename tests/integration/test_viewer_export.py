"""Verify the portable document against the observations and recorded SciPy fit."""

import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from elegant_spline import (
    BSplineCurvatureSmoothingParams,
    DistanceFitOptions,
    DistanceSplineFitter,
    FixedKnotSplineFitter,
    PlanarFitOptions,
    SmoothingSplineFitter,
    export_viewer_document,
)


POINTS = np.array([
    (0, 0), (0, 0), (0.05, 0), (1, 0.5), (1.7, 0.8), (2.2, 0.2),
    (1.7, 0.8), (2.5, 1.1), (3, 0.2),
])
OPTIONS = PlanarFitOptions(resample_spacing=0.11, merge_diameter=0.1)
DISTANCE = DistanceFitOptions(rms_allowance=0.075, resample_spacing=0.11, merge_diameter=0.1)
DOMAIN = {
    "outer": ((-1, -1), (4, -1), (4, 2), (-1, 2), (-1, -1)),
    "holes": [[(2, 0.5), (2.2, 0.8), (2, 0.8)]],
    "clearance": 0.05,
}


class ViewerExportTests(unittest.TestCase):
    def test_correspondence_for_all_planar_methods(self):
        fitters = (
            DistanceSplineFitter(DISTANCE),
            FixedKnotSplineFitter(knot_spacing=0.9, options=OPTIONS),
            SmoothingSplineFitter(smoothing_strength=0.001, options=OPTIONS),
        )
        for fitter in fitters:
            with self.subTest(fitter=type(fitter).__name__):
                result = fitter.fit(POINTS)
                exported = export_viewer_document(POINTS, result, domain=DOMAIN, unit="m")
                doc = json.loads(json.dumps(exported, allow_nan=False))
                self.assertEqual(doc["version"], 1)
                self.assertEqual(doc["unit"], "m")
                self.assertEqual(doc["domain"]["clearance"], 0.05)
                np.testing.assert_array_equal(doc["domain"]["holes"], DOMAIN["holes"])
                np.testing.assert_array_equal(doc["domain"]["outer"], DOMAIN["outer"][:-1])
                np.testing.assert_array_equal([o["xy"] for o in doc["observations"]], POINTS)
                np.testing.assert_array_equal(
                    [o["u"] for o in doc["observations"]], result.source_parameters
                )
                self.assertGreater(doc["observations"][6]["u"], doc["observations"][4]["u"])
                guide, recorded = result.report.guide, doc["preprocessing"]
                self.assertEqual(recorded["membership"], [0, 0, 0, 1, 2, 3, 4, 5, 6])
                self.assertEqual(recorded["membership"], list(guide.cluster_membership))
                np.testing.assert_array_equal(recorded["representatives"], guide.guide_points)
                np.testing.assert_array_equal(recorded["points"], guide.points)
                np.testing.assert_array_equal(recorded["parameters"], guide.parameters)
                self.assertEqual(doc["fit"]["method"], result.report.method)
                self.assertEqual(doc["fit"]["status"], "fitted")
                self.assertIsNone(doc["fit"]["reason"])
                self.assertEqual(set(doc["fit"]["stages"]), {"initial", "final"})

    def test_exact_geometry_on_nonuniform_spans(self):
        options = replace(DISTANCE, fairing=BSplineCurvatureSmoothingParams(
            lambda_curvature=0.01, fidelity_scale=0.15,
        ))
        result = DistanceSplineFitter(options).fit(POINTS)
        doc = export_viewer_document(POINTS, result)
        self.assertIsNone(doc["domain"])
        self.assertIsNone(doc["unit"])
        for name, spline in (
            ("initial", result.initial_curve),
            ("preFairing", result.pre_fairing_curve),
            ("final", result.curve),
        ):
            stage = doc["fit"]["stages"][name]
            np.testing.assert_array_equal(stage["controls"], spline.c)
            breaks = np.unique(spline.t)
            self.assertGreater(np.ptp(np.diff(breaks)), 0.05)
            self.assertEqual(len(stage["spans"]), len(breaks) - 1)
            for span, a, b in zip(stage["spans"], breaks[:-1], breaks[1:], strict=True):
                self.assertEqual((span["a"], span["b"]), (a, b))
                controls = np.asarray(span["points"])
                for t in (0, 0.18, 0.5, 0.77, 1):
                    u = a + t * (b - a)
                    s = 1 - t
                    value = np.array([s**3, 3*t*s**2, 3*s*t**2, t**3]) @ controls
                    derivative = 3 / (b - a) * np.array([s**2, 2*s*t, t**2]) @ np.diff(controls, axis=0)
                    np.testing.assert_allclose(value, spline(u), atol=1e-12)
                    np.testing.assert_allclose(derivative, spline(u, nu=1), atol=1e-11)

    def test_recovery_and_unavailable_results(self):
        fitter = DistanceSplineFitter(DistanceFitOptions(
            rms_allowance=0.1, resample_spacing=0.25, fallback="endpoint",
        ))
        for points, reason in (
            ([(1, 1)], "constant"),
            ([(8e307, 0)], "constant"),
            ([(1, 1), (2, 3)], "line"),
        ):
            with self.subTest(shape=reason):
                result = fitter.fit(points)
                fit = export_viewer_document(points, result)["fit"]
                self.assertEqual(fit["status"], "fallback")
                self.assertIn(reason, fit["reason"])
                self.assertIn(result.report.solver_reason, fit["reason"])
                self.assertEqual(set(fit["stages"]), {"final"})
                np.testing.assert_allclose(fit["stages"]["final"]["spans"][0]["points"],
                                           result.curve.c)
        result = DistanceSplineFitter(DISTANCE).fit([(4, 2)])
        doc = export_viewer_document([(4, 2)], result)
        self.assertEqual(doc["fit"]["status"], "unavailable")
        self.assertEqual(doc["fit"]["stages"], {})
        self.assertEqual(doc["fit"]["reason"], result.report.solver_reason)
        self.assertEqual(doc["preprocessing"]["points"], [[4, 2]])

    def test_invalid_export_input(self):
        result = DistanceSplineFitter(DISTANCE).fit(POINTS)
        with self.assertRaisesRegex(ValueError, "observation count"):
            export_viewer_document(POINTS[:-1], result)
        for field, value in (("clearance", float("inf")), ("clearance", -1),
                             ("outer", [[0, 0], [1, 2], [0, 0]])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                export_viewer_document(POINTS, result, domain=DOMAIN | {field: value})

    def test_reproduce_bundled_example(self):
        repo = Path(__file__).resolve().parents[2]
        expected = json.loads((repo / "web/spline-viewer/example.json").read_text())
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "example.json"
            subprocess.run([sys.executable, repo / "scripts/export_viewer_example.py", output],
                           check=True, capture_output=True, cwd=tempdir)
            actual = json.loads(output.read_text())
        self.assertEqual(actual["domain"], expected["domain"])
        for recorded, reference in zip(actual["observations"], expected["observations"], strict=True):
            self.assertEqual(recorded["xy"], reference["xy"])
            self.assertAlmostEqual(recorded["u"], reference["u"])
        self.assertEqual(actual["preprocessing"]["membership"], expected["preprocessing"]["membership"])
        for field in ("representatives", "points", "parameters"):
            np.testing.assert_allclose(actual["preprocessing"][field], expected["preprocessing"][field])
        self.assertEqual(set(actual["fit"]["stages"]), {"initial", "preFairing", "final"})
        for name, stage in actual["fit"]["stages"].items():
            reference = expected["fit"]["stages"][name]
            np.testing.assert_allclose(stage["controls"], reference["controls"], atol=1e-6)
            for span, ref in zip(stage["spans"], reference["spans"], strict=True):
                np.testing.assert_allclose([span["a"], span["b"]], [ref["a"], ref["b"]])
                np.testing.assert_allclose(span["points"], ref["points"], atol=1e-6)
