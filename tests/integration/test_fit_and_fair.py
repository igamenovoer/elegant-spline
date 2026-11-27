"""Check the fitting and fairing stages through the public API."""

from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from elegant_spline import (
    BSplineCurvatureSmoother,
    BSplineCurvatureSmoothingParams,
    DistanceFitOptions,
    DistanceSplineFitter,
)


def _hairpin():
    outbound = np.column_stack((np.linspace(0.0, 4.0, 60), np.zeros(60)))
    angle = np.linspace(0.0, np.pi, 41)
    bend = np.column_stack((4.0 + 0.35 * np.sin(angle), 0.35 - 0.35 * np.cos(angle)))
    inbound = np.column_stack((np.linspace(4.0, 0.0, 60), np.full(60, 0.7)))
    return np.vstack((outbound, bend[1:], inbound))


def _options():
    return DistanceFitOptions(
        rms_allowance=0.15,
        resample_spacing=0.1,
        merge_diameter=0.1,
        endpoint_weight_multiplier=4.0,
        fairing=BSplineCurvatureSmoothingParams(
            lambda_curvature=0.01,
            fidelity_scale=0.1,
            outside_scale=0.05,
            region_mode="auto",
            curvature_threshold=2.0,
        ),
    )


class FitAndFairTests(unittest.TestCase):
    def test_verified_fairing_follows_correction_and_measures_the_final_curve(self):
        points = _hairpin()
        original_smooth = BSplineCurvatureSmoother.smooth_with_report
        calls = []

        def record(smoother, spline, points=None, parameters=None, weights=None, regions=None):
            calls.append((spline, points, parameters, weights, regions))
            return original_smooth(smoother, spline, points, parameters, weights, regions)

        with patch.object(
            BSplineCurvatureSmoother, "smooth_with_report", autospec=True, side_effect=record
        ):
            result = DistanceSplineFitter(_options()).fit(points)

        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.fairing_status, "completed")
        self.assertEqual(len(calls), 1)
        initial = result.initial_curve
        pre_fairing = result.pre_fairing_curve
        final = result.curve
        self.assertIsNotNone(initial)
        self.assertIsNotNone(pre_fairing)
        self.assertIsNotNone(final)
        supplied, observations, parameters, weights, regions = calls[0]
        guide = result.report.guide
        np.testing.assert_array_equal(observations, guide.points)
        np.testing.assert_array_equal(parameters, guide.parameters)
        if weights is not None:
            np.testing.assert_array_equal(weights, np.ones(len(guide.points)))
        self.assertIsNone(regions)

        ends = [0.0, 1.0]
        probes = np.linspace(0.0, 1.0, 65)
        self.assertGreater(float(np.max(np.abs(initial(ends) - points[[0, -1]]))), 1e-8)
        np.testing.assert_allclose(supplied(ends), points[[0, -1]], atol=1e-9)
        np.testing.assert_allclose(supplied(probes), pre_fairing(probes), atol=1e-12)
        np.testing.assert_array_equal(final.t, pre_fairing.t)
        np.testing.assert_allclose(final(ends), pre_fairing(ends), atol=1e-9)
        np.testing.assert_allclose(final(ends, nu=1), pre_fairing(ends, nu=1), atol=1e-8)
        self.assertGreater(float(np.max(np.abs(final(probes) - pre_fairing(probes)))), 1e-8)

        residual = final(guide.parameters) - np.asarray(guide.points)
        weighted_sum = np.sum((np.asarray(guide.weights)[:, None] * residual) ** 2)
        self.assertAlmostEqual(result.report.final_metrics.weighted_residual_sum, weighted_sum)

    def test_disabled_fairing_and_endpoint_recovery_skip_the_smoother(self):
        options = _options()
        with patch.object(BSplineCurvatureSmoother, "smooth_with_report") as smooth:
            disabled = DistanceSplineFitter(replace(options, fairing=None)).fit(_hairpin())
            recovery = DistanceSplineFitter(
                replace(options, maximum_fit_attempts=0, fallback="endpoint")
            ).fit(_hairpin())

        smooth.assert_not_called()
        self.assertEqual(disabled.status, "fitted")
        self.assertEqual(disabled.report.fairing_status, "disabled")
        self.assertIsNone(disabled.pre_fairing_curve)
        self.assertEqual(recovery.status, "fallback")
        self.assertEqual(recovery.report.fairing_status, "skipped")

    def test_failed_fairing_retains_the_input_to_fairing(self):
        with patch.object(
            BSplineCurvatureSmoother,
            "smooth_with_report",
            side_effect=FloatingPointError("unusable numerical trial"),
        ) as smooth:
            result = DistanceSplineFitter(_options()).fit(_hairpin())

        smooth.assert_called_once()
        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.fairing_status, "failed")
        self.assertIsNotNone(result.pre_fairing_curve)
        self.assertIsNotNone(result.curve)
        probes = np.linspace(0.0, 1.0, 65)
        np.testing.assert_array_equal(result.curve(probes), result.pre_fairing_curve(probes))

    def test_integrated_fairing_requires_position_and_tangent_preservation(self):
        options = _options()
        for policy in ("free", "position"):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                replace(options, fairing=replace(options.fairing, endpoint_policy=policy))
