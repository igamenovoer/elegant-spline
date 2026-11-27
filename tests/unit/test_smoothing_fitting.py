"""Numerical and recovery checks for planar smoothing splines."""

from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
from scipy.interpolate import make_smoothing_spline

from elegant_spline import PlanarFitOptions, SmoothingSplineFitter


POINTS = np.array(
    [(0.0, 0.0), (1.1, 0.7), (1.7, -0.3), (2.4, 1.3), (3.4, 1.7), (4.1, 0.2)]
)
OPTIONS = PlanarFitOptions(resample_spacing=0.37, endpoint_weight_multiplier=3.0)
SMOOTHING_STRENGTH = 0.004


class SmoothingFittingTests(unittest.TestCase):
    def test_weighted_fit_matches_independent_scalar_scipy_references(self):
        result = SmoothingSplineFitter(
            smoothing_strength=SMOOTHING_STRENGTH, options=OPTIONS
        ).fit(POINTS)
        self.assertEqual(result.status, "fitted")
        report = result.report
        self.assertEqual(report.method, "smoothing")
        self.assertEqual(report.smoothing_strength, SMOOTHING_STRENGTH)
        self.assertEqual(report.solver_attempts, 1)
        self.assertIsNone(report.residual_budget)
        self.assertIsNone(report.initial_metrics.budget_met)
        self.assertIsNone(report.final_metrics.budget_met)

        parameters = np.asarray(report.guide.parameters)
        weights = np.square(report.guide.weights)
        self.assertGreater(np.ptp(weights), 0.0)
        probes = np.linspace(0.0, 1.0, 65)
        expected = np.column_stack(
            [
                make_smoothing_spline(
                    parameters, coordinate, w=weights, lam=SMOOTHING_STRENGTH
                )(probes)
                for coordinate in np.asarray(report.guide.points).T
            ]
        )
        np.testing.assert_allclose(result.initial_curve(probes), expected, atol=1e-10, rtol=1e-10)

    def test_zero_strength_interpolates_prepared_guide(self):
        result = SmoothingSplineFitter(smoothing_strength=0.0, options=OPTIONS).fit(POINTS)
        self.assertEqual(result.status, "fitted")
        guide = result.report.guide
        np.testing.assert_allclose(result.initial_curve(guide.parameters), guide.points, atol=1e-10)

    def test_four_prepared_points_skip_solve(self):
        result = SmoothingSplineFitter(
            smoothing_strength=SMOOTHING_STRENGTH,
            options=replace(OPTIONS, maximum_fit_points=4),
        ).fit(POINTS)
        self.assertEqual(len(result.report.guide.points), 4)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.report.solver_status, "skipped")
        self.assertEqual(result.report.solver_reason, "insufficient_observations")
        self.assertEqual(result.report.solver_attempts, 0)
        self.assertIsNone(result.curve)

    def test_five_prepared_points_allow_one_attempt(self):
        result = SmoothingSplineFitter(
            smoothing_strength=SMOOTHING_STRENGTH,
            options=replace(OPTIONS, maximum_fit_points=5),
        ).fit(POINTS)
        self.assertEqual(len(result.report.guide.points), 5)
        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.solver_attempts, 1)

    def test_invalid_smoothing_strength_is_rejected(self):
        for strength in (True, "0.1", -0.1, np.inf, np.nan):
            with self.subTest(strength=strength), self.assertRaises((TypeError, ValueError)):
                SmoothingSplineFitter(smoothing_strength=strength, options=OPTIONS)

    def test_second_coordinate_failure_discards_partial_fit(self):
        with patch("elegant_spline.distance_fitting.make_smoothing_spline") as solve:
            def fail_second_coordinate(*args, **kwargs):
                if solve.call_count == 2:
                    raise ValueError("second-axis solver failed")
                return make_smoothing_spline(*args, **kwargs)

            solve.side_effect = fail_second_coordinate
            result = SmoothingSplineFitter(
                smoothing_strength=SMOOTHING_STRENGTH, options=OPTIONS
            ).fit(POINTS)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.report.solver_status, "failed")
        self.assertEqual(result.report.solver_attempts, 1)
        self.assertIn("second-axis solver failed", result.report.solver_reason)
        self.assertIsNone(result.initial_curve)
        self.assertIsNone(result.curve)

    def test_unusable_squared_weights_use_requested_endpoint_recovery(self):
        options = replace(OPTIONS, endpoint_weight_multiplier=1e-200, fallback="endpoint")
        result = SmoothingSplineFitter(
            smoothing_strength=SMOOTHING_STRENGTH, options=options
        ).fit(POINTS)
        guide_weights = np.asarray(result.report.guide.weights)
        self.assertTrue(np.all(guide_weights > 0))
        self.assertEqual(float(guide_weights[0]) ** 2, 0.0)
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.report.solver_status, "failed")
        self.assertEqual(result.report.solver_attempts, 1)
        self.assertEqual(result.report.recovery, "line")
        self.assertIsNone(result.initial_curve)
        np.testing.assert_array_equal(result.curve([0.0, 1.0]), POINTS[[0, -1]])
