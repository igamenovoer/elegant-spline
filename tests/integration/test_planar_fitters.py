"""Check the shared fit and fairing stages through the public planar APIs."""

import unittest

import numpy as np

from elegant_spline import (
    BSplineCurvatureSmoothingParams,
    FixedKnotSplineFitter,
    PlanarFitOptions,
    SmoothingSplineFitter,
)


class PlanarFittersIntegrationTests(unittest.TestCase):
    def test_fitters_share_guide_options_and_measure_the_corrected_curve(self):
        points = np.array(
            [
                (0.0, 0.0), (0.0, 0.0), (0.05, 0.0), (1.0, 0.5), (1.7, 0.8),
                (2.2, 0.2), (1.7, 0.8), (2.5, 1.1), (3.0, 0.2),
            ]
        )
        original = points.copy()
        options = PlanarFitOptions(
            resample_spacing=0.1,
            merge_diameter=0.1,
            endpoint_weight_multiplier=2.0,
            maximum_fit_points=12,
        )
        smoothing = SmoothingSplineFitter(smoothing_strength=0.001, options=options).fit(points)
        fixed = FixedKnotSplineFitter(knot_spacing=1.0, options=options).fit(points)
        np.testing.assert_array_equal(points, original)
        guide = smoothing.report.guide
        self.assertEqual(guide, fixed.report.guide)
        self.assertEqual(guide.cluster_membership, (0, 0, 0, 1, 2, 3, 4, 5, 6))
        self.assertTrue(guide.cap_applied)
        self.assertEqual(guide.requested_spacing, 0.1)
        self.assertEqual(len(guide.points), 12)
        self.assertAlmostEqual(guide.effective_spacing, guide.length / 11)
        np.testing.assert_array_equal([guide.points[0], guide.points[-1]], [(0.025, 0), (3, 0.2)])
        self.assertAlmostEqual(guide.weights[0] / guide.weights[1], 2 / np.sqrt(2))
        self.assertAlmostEqual(np.linalg.norm(guide.weights) ** 2, 12)

        source_distances = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        source_progress = source_distances / source_distances[-1]
        guide_weights = np.asarray(guide.weights)
        for result in (smoothing, fixed):
            with self.subTest(method=result.report.method):
                self.assertEqual(result.status, "fitted")
                self.assertEqual(result.report.correction_status, "completed")
                np.testing.assert_allclose(result.source_parameters, source_progress)
                self.assertEqual(result.source_parameters[0], result.source_parameters[1])
                self.assertGreater(result.source_parameters[6], result.source_parameters[4])
                curve = result.curve
                self.assertEqual(curve.k, 3)
                self.assertFalse(curve.extrapolate)
                np.testing.assert_array_equal(curve.t[:4], [0.0] * 4)
                np.testing.assert_array_equal(curve.t[-4:], [1.0] * 4)
                np.testing.assert_allclose(curve([0.0, 1.0]), points[[0, -1]], atol=1e-9, rtol=0)
                interior = curve.t[4:-4]
                self.assertGreater(len(interior), 0)
                for order in range(3):
                    np.testing.assert_allclose(
                        curve(np.nextafter(interior, 0.0), nu=order),
                        curve(np.nextafter(interior, 1.0), nu=order),
                        atol=1e-9,
                        rtol=1e-9,
                    )

                self.assertIsNone(result.report.residual_budget)
                for fitted, metrics in (
                    (result.initial_curve, result.report.initial_metrics),
                    (curve, result.report.final_metrics),
                ):
                    source_error = np.linalg.norm(fitted(source_progress) - points, axis=1)
                    guide_error = fitted(guide.parameters) - guide.points
                    weighted_sum = np.sum((guide_weights[:, None] * guide_error) ** 2)
                    self.assertAlmostEqual(metrics.source_rms, np.sqrt(np.mean(source_error**2)))
                    self.assertAlmostEqual(metrics.max_source_error, np.max(source_error))
                    self.assertAlmostEqual(metrics.weighted_residual_sum, weighted_sum)
                    self.assertAlmostEqual(
                        metrics.weighted_rms, np.sqrt(weighted_sum / np.sum(guide_weights**2))
                    )
                    self.assertIsNone(metrics.budget_met)

    def test_fixed_knot_fairing_preserves_the_corrected_endpoints_and_tangents(self):
        x = np.linspace(0.0, 4.0, 35)
        points = np.column_stack((x, 0.5 * np.sin(x)))
        options = PlanarFitOptions(
            resample_spacing=0.15,
            fairing=BSplineCurvatureSmoothingParams(lambda_curvature=0.05, fidelity_scale=0.1),
        )
        result = FixedKnotSplineFitter(knot_spacing=0.75, options=options).fit(points)
        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.correction_status, "completed")
        self.assertEqual(result.report.fairing_status, "completed")
        before = result.pre_fairing_curve
        after = result.curve
        ends = [0.0, 1.0]
        np.testing.assert_array_equal(after.t, before.t)
        np.testing.assert_allclose(before(ends), points[[0, -1]], atol=1e-9, rtol=0)
        np.testing.assert_allclose(after(ends), before(ends), atol=1e-9, rtol=0)
        np.testing.assert_allclose(after(ends, nu=1), before(ends, nu=1), atol=1e-8, rtol=0)
        samples = np.linspace(0.0, 1.0, 33)
        self.assertGreater(np.max(np.abs(after(samples) - before(samples))), 1e-8)
        guide = result.report.guide
        residual = after(guide.parameters) - guide.points
        weighted_sum = np.sum((np.asarray(guide.weights)[:, None] * residual) ** 2)
        self.assertAlmostEqual(result.report.final_metrics.weighted_residual_sum, weighted_sum)
