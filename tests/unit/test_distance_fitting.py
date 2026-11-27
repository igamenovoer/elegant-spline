"""Unit checks for planar fitting using synthetic coordinates."""

from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

import numpy as np
from scipy.interpolate import BSpline, make_splprep

from elegant_spline.distance_fitting import DistanceFitOptions, DistanceSplineFitter


POINTS = np.array(
    [(0.0, 0.0), (3.0, 0.0), (4.0, 1.0), (5.0, -0.4), (6.0, 4.0), (7.0, 4.0)]
)
OPTIONS = DistanceFitOptions(rms_allowance=0.15, resample_spacing=0.1)


class GuidePreparationTests(unittest.TestCase):
    def test_setting_validation_and_immutability(self):
        with self.assertRaises(FrozenInstanceError):
            setattr(OPTIONS, "rms_allowance", 0.1)
        for settings in (
            {"rms_allowance": 0.0},
            {"rms_allowance": True},
            {"resample_spacing": np.inf},
            {"merge_diameter": -0.1},
            {"endpoint_weight_multiplier": 0.0},
            {"maximum_fit_points": 3},
            {"maximum_fit_attempts": 2},
            {"maximum_fit_attempts": 1.0},
            {"correct_endpoints": "yes"},
            {"fallback": "arbitrary"},
        ):
            with self.subTest(settings=settings), self.assertRaises((TypeError, ValueError)):
                replace(OPTIONS, **settings)

    def test_invalid_input_is_rejected_before_solve(self):
        fitter = DistanceSplineFitter(OPTIONS)
        with patch("elegant_spline.distance_fitting.make_splprep") as solve:
            for points in ([], [[1]], [[1, 2, 3]], [[1, np.nan]], [[1 + 2j, 0]], [["1", "0"]]):
                with self.subTest(points=points), self.assertRaisesRegex(ValueError, "coordinate"):
                    fitter.fit(points)
            with self.assertRaisesRegex(ValueError, "cumulative chord distance"):
                fitter.fit([[1e308, 0], [-1e308, 0]])
        solve.assert_not_called()

    def test_whole_group_diameter_and_source_chord_parameters(self):
        source = np.array([(0, 0), (0, 0), (0.4, 0), (0.8, 0), (1.2, 0), (0, 0)])
        original = source.copy()
        options = replace(OPTIONS, merge_diameter=0.5, maximum_fit_attempts=0)
        result = DistanceSplineFitter(options).fit(source)
        guide = result.report.guide
        np.testing.assert_array_equal(source, original)
        self.assertEqual(guide.unique_count, 5)
        self.assertEqual(guide.cluster_membership, (0, 0, 0, 1, 1, 2))
        np.testing.assert_allclose(guide.guide_points, [(0.2, 0), (1.0, 0), (0, 0)])
        np.testing.assert_allclose(guide.cluster_diameters, (0.4, 0.4, 0.0))
        self.assertAlmostEqual(guide.detail_loss, 0.2)
        np.testing.assert_allclose(result.source_parameters, [0, 0, 1 / 6, 1 / 3, 1 / 2, 1])

    def test_capped_resampling_keeps_guide_endpoints(self):
        options = replace(OPTIONS, maximum_fit_points=8, maximum_fit_attempts=0)
        guide = DistanceSplineFitter(options).fit(POINTS).report.guide
        self.assertTrue(guide.cap_applied)
        self.assertEqual(len(guide.points), 8)
        self.assertEqual(guide.parameters[0], 0.0)
        self.assertEqual(guide.parameters[-1], 1.0)
        np.testing.assert_array_equal([guide.points[0], guide.points[-1]], POINTS[[0, -1]])
        self.assertAlmostEqual(guide.effective_spacing, guide.length / 7)
        self.assertAlmostEqual(np.linalg.norm(guide.weights) ** 2, 8.0)

    def test_extreme_endpoint_weights_stay_positive_and_normalized(self):
        for multiplier in (1e-161, 1e308):
            with self.subTest(multiplier=multiplier):
                options = replace(OPTIONS, resample_spacing=2.0, endpoint_weight_multiplier=multiplier)
                guide = DistanceSplineFitter(options).fit([[0.0, 0.0], [1.0, 0.0]]).report.guide
                self.assertEqual(guide.weight_adjustment, "log_normalization")
                self.assertTrue(np.all(np.asarray(guide.weights) > 0))
                self.assertAlmostEqual(np.linalg.norm(guide.weights) ** 2, 2.0)


class DistanceFittingTests(unittest.TestCase):
    def test_weighted_fit_matches_independent_scipy_reference(self):
        option = replace(OPTIONS, endpoint_weight_multiplier=2.0)
        result = DistanceSplineFitter(option).fit(POINTS)
        self.assertEqual(result.status, "fitted")

        source_lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(POINTS, axis=0), axis=1))]
        locations = np.r_[np.arange(0.0, source_lengths[-1], option.resample_spacing), source_lengths[-1]]
        guide_points = np.array(
            [np.interp(locations, source_lengths, axis) for axis in POINTS.T]
        )
        parameters = locations / source_lengths[-1]
        intervals = np.diff(parameters)
        support = np.r_[intervals[0], intervals[:-1] + intervals[1:], intervals[-1]] / 2
        weights = support**0.5
        weights[[0, -1]] *= option.endpoint_weight_multiplier
        weights = weights / np.linalg.norm(weights) * len(parameters) ** 0.5
        budget = len(parameters) * option.rms_allowance**2
        reference, _ = make_splprep(guide_points, u=parameters, k=3, w=weights, s=budget)

        samples = np.linspace(0.0, 1.0, 65)
        sampled_reference = np.moveaxis(reference(samples), reference.axis, 0)
        np.testing.assert_allclose(
            result.initial_curve(samples), sampled_reference, atol=1e-10, rtol=1e-10
        )
        np.testing.assert_allclose(result.report.guide.points, guide_points.T, atol=1e-12)
        np.testing.assert_allclose(result.report.guide.weights, weights, atol=1e-12)
        self.assertAlmostEqual(result.report.residual_budget, budget)

        offsets = POINTS[[0, -1]] - np.moveaxis(reference([0.0, 1.0]), reference.axis, 0)
        expected = (
            sampled_reference + (1 - samples[:, None]) * offsets[0] + samples[:, None] * offsets[1]
        )
        np.testing.assert_allclose(result.curve(samples), expected, atol=1e-10, rtol=1e-10)

    def test_c2_endpoints_and_budget_miss_are_measured(self):
        options = replace(OPTIONS, rms_allowance=0.142)
        result = DistanceSplineFitter(options).fit(POINTS)
        final = result.curve
        self.assertIsInstance(final, BSpline)
        self.assertFalse(final.extrapolate)
        np.testing.assert_allclose(final([0.0, 1.0]), POINTS[[0, -1]], atol=1e-9, rtol=0)
        interior = final.t[4:-4]
        self.assertGreater(len(interior), 0)
        for derivative in range(3):
            np.testing.assert_allclose(
                final(np.nextafter(interior, 0.0), nu=derivative),
                final(np.nextafter(interior, 1.0), nu=derivative),
                atol=1e-9,
                rtol=1e-9,
            )
        self.assertLessEqual(max(result.report.final_metrics.endpoint_errors), 1e-9)
        self.assertTrue(result.report.initial_metrics.budget_met)
        self.assertGreater(result.report.final_metrics.weighted_rms, options.rms_allowance)
        self.assertFalse(result.report.final_metrics.budget_met)

    def test_source_and_guide_errors_use_their_own_reference(self):
        result = DistanceSplineFitter(OPTIONS).fit(POINTS)
        final = result.curve
        report = result.report
        guide = report.guide
        source_error = np.linalg.norm(final(result.source_parameters) - POINTS, axis=1)
        guide_error = final(guide.parameters) - guide.points
        weighted_sum = np.sum(np.asarray(guide.weights)[:, None] ** 2 * guide_error**2)
        self.assertAlmostEqual(report.final_metrics.source_rms, float(np.mean(source_error**2)**0.5))
        self.assertAlmostEqual(report.final_metrics.max_source_error, float(np.max(source_error)))
        self.assertAlmostEqual(report.final_metrics.weighted_residual_sum, weighted_sum)
        self.assertAlmostEqual(report.final_metrics.weighted_rms, (weighted_sum / sum(np.asarray(guide.weights)**2))**0.5)
        self.assertNotAlmostEqual(report.initial_metrics.weighted_rms, report.final_metrics.weighted_rms)
        self.assertIsNone(result.pre_fairing_curve)
        self.assertEqual(report.fairing_status, "disabled")

    def test_short_input_and_zero_attempt_budget_skip_the_solver(self):
        short = DistanceSplineFitter(OPTIONS).fit([[0, 0], [1, 2]])
        capped = DistanceSplineFitter(replace(OPTIONS, maximum_fit_attempts=0)).fit(POINTS)
        for result, reason in (
            (short, "insufficient_observations"),
            (capped, "attempt_budget_exhausted"),
        ):
            self.assertEqual(result.status, "unavailable")
            self.assertIsNone(result.curve)
            self.assertIsNone(result.initial_curve)
            self.assertEqual(result.report.solver_status, "skipped")
            self.assertEqual(result.report.solver_attempts, 0)
            self.assertEqual(result.report.solver_reason, reason)

    def test_solver_failure_is_reported_without_implicit_recovery(self):
        with patch(
            "elegant_spline.distance_fitting.make_splprep", side_effect=ValueError("failed solver")
        ) as solve:
            result = DistanceSplineFitter(OPTIONS).fit(POINTS)
        solve.assert_called_once()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.report.solver_status, "failed")
        self.assertEqual(result.report.solver_attempts, 1)
        self.assertIn("failed solver", result.report.solver_reason)
        self.assertIsNone(result.curve)
        self.assertIsNone(result.report.final_metrics)

    def test_failed_correction_retains_initial_geometry(self):
        with patch(
            "elegant_spline.distance_fitting._correct_endpoints",
            side_effect=ValueError("failed correction"),
        ):
            result = DistanceSplineFitter(OPTIONS).fit(POINTS)
        self.assertEqual(result.status, "fitted")
        self.assertIs(result.curve, result.initial_curve)
        self.assertEqual(result.report.correction_status, "failed")
        self.assertIn("failed correction", result.report.correction_reason)
        self.assertEqual(result.report.final_metrics, result.report.initial_metrics)

    def test_requested_recovery_preserves_endpoints_and_measures_original_points(self):
        fitter = DistanceSplineFitter(replace(OPTIONS, maximum_fit_attempts=0, fallback="endpoint"))
        closed = fitter.fit([[2, 3], [5, 6], [2, 3]])
        self.assertEqual(closed.status, "fallback")
        self.assertEqual(closed.report.recovery, "constant")
        self.assertEqual(closed.source_parameters, (0.0, 0.5, 1.0))
        np.testing.assert_allclose(closed.curve([0.0, 0.5, 1.0]), [[2, 3]] * 3)
        self.assertAlmostEqual(closed.report.final_metrics.source_rms, np.sqrt(6))
        self.assertAlmostEqual(closed.report.final_metrics.max_source_error, np.sqrt(18))

        line = fitter.fit([[1, 2], [3, 4]])
        self.assertEqual(line.status, "fallback")
        self.assertEqual(line.report.recovery, "line")
        np.testing.assert_allclose(line.curve([0.0, 0.5, 1.0]), [[1, 2], [2, 3], [3, 4]])

        constant = fitter.fit([[2, 3]])
        self.assertEqual(constant.source_parameters, (0.0,))
        self.assertEqual(constant.report.recovery, "constant")
        np.testing.assert_allclose(constant.curve([0.0, 0.5, 1.0]), [[2, 3]] * 3)
