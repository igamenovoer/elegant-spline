"""Verify fixed-knot fairing with synthetic vector splines."""

import json
import unittest
from dataclasses import FrozenInstanceError, replace

import numpy as np
from scipy.interpolate import BSpline

from elegant_spline.curvature_smoothing import (
    BSplineCurvatureSmoother,
    BSplineCurvatureSmoothingParams,
    BSplineSmoothingError,
)


def _settings(**changes):
    return replace(
        BSplineCurvatureSmoothingParams(
            lambda_curvature=0.01,
            fidelity_scale=0.1,
            region_mode="auto",
            curvature_threshold=2.0,
            outside_scale=0.05,
        ),
        **changes,
    )


def _bent_spline():
    knots = np.r_[np.zeros(4), np.linspace(0, 1, 10)[1:-1], np.ones(4)]
    controls = np.column_stack((np.linspace(0, 10, 12), np.zeros(12)))
    controls[5, 1] = 2.0
    return BSpline(knots, controls, 3, extrapolate=False)


class CurvatureSmoothingTests(unittest.TestCase):
    def test_settings_are_immutable_and_validated(self):
        settings = _settings()
        with self.assertRaises(FrozenInstanceError):
            settings.lambda_curvature = 0.0
        malformed = (
            {"fidelity_scale": 0.0},
            {"outside_scale": -1.0},
            {"lambda_curvature": np.nan},
            {"lambda_curvature": True},
            {"max_nfev": 3.0},
            {"curvature_threshold": None},
            {"endpoint_policy": "unknown"},
        )
        for changes in malformed:
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                _settings(**changes)

    def test_malformed_observations_fail_before_solving(self):
        spline = _bent_spline()
        smoother = BSplineCurvatureSmoother(_settings())
        invalid = (
            {"points": [[0.0, 0.0]]},
            {"parameters": [0.0]},
            {"points": [[0.0, 0.0]], "parameters": [1.1]},
            {"points": [[0.0, 0.0]], "parameters": [0.0, 0.2]},
            {"points": [[0.0, np.nan]], "parameters": [0.2]},
            {"points": [[0.0, 0.0]], "parameters": [0.2], "weights": [0.0]},
            {"points": [[1j, 0.0]], "parameters": [0.2]},
            {"regions": [(0.8, 0.2)]},
        )
        for options in invalid:
            with self.subTest(options=options), self.assertRaises((TypeError, ValueError)):
                smoother.smooth_with_report(spline, **options)

    def test_unsupported_splines_are_rejected(self):
        spline = _bent_spline()
        smoother = BSplineCurvatureSmoother(_settings())
        for invalid, reason in (
            (BSpline(spline.t, spline.c[:, 0], spline.k), "scalar"),
            (BSpline(spline.t, spline.c[:, :, None], spline.k), "tensor"),
            (BSpline(spline.t, spline.c.astype(complex) + 1j, spline.k), "real"),
            (BSpline(spline.t, spline.c, spline.k, extrapolate="periodic"), "periodic"),
            (BSpline([0] * 4 + [0.5, 0.5] + [1] * 4, np.zeros((6, 2)), 3), "multiplicity"),
            (BSpline([0] * 3 + [1] * 3, np.zeros((3, 2)), 2), "degree"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                smoother.smooth_with_report(invalid)

    def test_coordinate_layout_domain_and_inputs_are_preserved(self):
        spline = _bent_spline()
        knots = 2.0 + 3.0 * spline.t
        point_first = BSpline(knots, spline.c, spline.k, extrapolate=True)
        coordinate_first = BSpline(knots, spline.c.T, spline.k, axis=1, extrapolate=True)
        parameters = np.linspace(2, 5, 101)
        points = point_first(parameters)
        weights = np.linspace(1, 2, len(points))
        inputs = (point_first.t, point_first.c, coordinate_first.c, points, parameters, weights)
        originals = [values.copy() for values in inputs]

        smoother = BSplineCurvatureSmoother(_settings())
        first = smoother.smooth_with_report(point_first, points, parameters, weights)
        second = smoother.smooth_with_report(coordinate_first, points, parameters, weights)

        self.assertEqual(first.report.outcome, "completed")
        self.assertEqual(second.report.outcome, "completed")
        self.assertEqual(first.spline.axis, 0)
        self.assertEqual(second.spline.axis, 1)
        self.assertTrue(second.spline.extrapolate)
        self.assertEqual(first.spline.k, point_first.k)
        np.testing.assert_array_equal(first.spline.t, knots)
        np.testing.assert_array_equal(second.spline.t, knots)
        np.testing.assert_allclose(first.spline(parameters), second.spline(parameters).T)
        for values, original in zip(inputs, originals, strict=True):
            np.testing.assert_array_equal(values, original)
        self.assertFalse(np.shares_memory(first.spline.c, point_first.c))

    def test_endpoint_constraints_use_unclamped_values(self):
        parameter_grid = np.linspace(0, 3, 16)
        controls = np.column_stack(
            (
                np.linspace(0, 5, 12),
                np.sin(np.linspace(0, 4, 12)) ** 2,
                np.cos(np.linspace(0, 3, 12)),
            )
        )
        spline = BSpline(parameter_grid, controls, 3, extrapolate=False)
        endpoints = [parameter_grid[3], parameter_grid[12]]
        for policy in ("free", "position", "position_and_tangent"):
            with self.subTest(policy=policy):
                result = BSplineCurvatureSmoother(
                    _settings(region_mode="all", endpoint_policy=policy, lambda_curvature=0.05)
                ).smooth_with_report(spline)
                self.assertEqual(result.report.outcome, "completed")
                if policy != "free":
                    np.testing.assert_allclose(
                        result.spline(endpoints), spline(endpoints), rtol=0, atol=1e-9
                    )
                if policy == "position_and_tangent":
                    np.testing.assert_allclose(
                        result.spline(endpoints, nu=1),
                        spline(endpoints, nu=1),
                        rtol=0,
                        atol=1e-9,
                    )

    def test_explicit_overlapping_regions_override_detection(self):
        spline = _bent_spline()
        smoother = BSplineCurvatureSmoother(_settings(curvature_threshold=100))
        first = smoother.smooth_with_report(spline, regions=[(0.5, 0.8), (0.2, 0.6)])
        second = smoother.smooth_with_report(spline, regions=[(0.2, 0.6), (0.5, 0.8)])
        self.assertEqual(first.report.outcome, "completed")
        self.assertEqual(first.report.regions.selected, [(0.2, 0.8)])
        self.assertEqual(first.report.regions, second.report.regions)
        self.assertFalse(first.report.detection.performed)
        np.testing.assert_array_equal(first.spline.c, second.spline.c)

    def test_automatic_selection_uses_the_curvature_threshold(self):
        spline = _bent_spline()
        result = BSplineCurvatureSmoother(_settings()).smooth_with_report(spline)
        self.assertEqual(result.report.outcome, "completed")
        self.assertTrue(result.report.detection.performed)
        self.assertEqual(len(result.report.regions.selected), 1)
        lo, hi = result.report.regions.selected[0]
        self.assertLess(lo, 0.45)
        self.assertGreater(hi, 0.45)

    def test_empty_regions_and_pinned_control_support_skip_solves(self):
        spline = _bent_spline()
        smoother = BSplineCurvatureSmoother(_settings(curvature_threshold=100))
        for regions in (None, []):
            with self.subTest(regions=regions):
                result = smoother.smooth_with_report(spline, regions=regions)
                self.assertEqual(result.report.outcome, "unchanged")
                self.assertEqual(result.report.reason, "no_regions")
                self.assertFalse(result.report.initialization.performed)
                self.assertFalse(result.report.main_solve.performed)
                np.testing.assert_array_equal(result.spline.c, spline.c)
        tiny = BSpline([0] * 4 + [1] * 4, [[0, 0], [1, 2], [2, 2], [3, 0]], 3)
        pinned = BSplineCurvatureSmoother(_settings(region_mode="all")).smooth_with_report(tiny)
        self.assertEqual(pinned.report.outcome, "unchanged")
        self.assertEqual(pinned.report.reason, "no_free_controls")
        self.assertFalse(pinned.report.main_solve.performed)
        np.testing.assert_array_equal(pinned.spline.c, tiny.c)

    def test_repeated_parameter_keeps_both_weighted_observations(self):
        spline = _bent_spline()
        parameters = np.linspace(0, 1, 21)
        parameters[5] = parameters[4]
        points = spline(parameters)
        expected = points[4].copy()
        points[4, 1] += 0.3
        points[5, 1] -= 0.1
        weights = np.ones(len(points))
        weights[5] = 3.0
        settings = _settings(
            lambda_curvature=0.0,
            outside_weight=0.0,
            initialization="original",
            region_mode="all",
        )
        result = BSplineCurvatureSmoother(settings).smooth_with_report(
            spline, points, parameters, weights
        )
        self.assertEqual(result.report.outcome, "completed")
        np.testing.assert_allclose(result.spline(parameters[4]), expected, rtol=0, atol=1e-8)
        residuals = result.spline(parameters) - points
        rms = np.sqrt(np.average(np.sum(residuals**2, axis=1), weights=weights))
        self.assertGreater(rms, 0)
        self.assertAlmostEqual(result.report.measurements.reference_error.after.value, rms)

    def test_rigid_transform_preserves_fidelity_and_geometric_bending(self):
        spline = _bent_spline()
        parameters = np.linspace(0, 1, 101)
        points = spline(parameters)
        angle = 0.7
        rotation = np.array(
            [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
        )
        translation = [3.0, -2.0]
        transformed = BSpline(spline.t, spline.c @ rotation.T + translation, spline.k)
        smoother = BSplineCurvatureSmoother(_settings())

        first = smoother.smooth_with_report(spline, points, parameters)
        second = smoother.smooth_with_report(
            transformed, points @ rotation.T + translation, parameters
        )

        self.assertEqual(first.report.outcome, "completed")
        self.assertEqual(second.report.outcome, "completed")
        np.testing.assert_allclose(
            second.spline(parameters),
            first.spline(parameters) @ rotation.T + translation,
            atol=1e-6,
            rtol=0,
        )
        first_values = [
            first.report.measurements.reference_error.after.value,
            first.report.measurements.bending_energy.after.value,
        ]
        second_values = [
            second.report.measurements.reference_error.after.value,
            second.report.measurements.bending_energy.after.value,
        ]
        np.testing.assert_allclose(first_values, second_values, atol=1e-9, rtol=1e-6)

        audit_parameters = np.linspace(0, 1, 20001)
        tangent = first.spline(audit_parameters, nu=1)
        second_derivative = first.spline(audit_parameters, nu=2)
        speed = np.linalg.norm(tangent, axis=1)
        cross = tangent[:, 0] * second_derivative[:, 1] - tangent[:, 1] * second_derivative[:, 0]
        bending = first.report.original_length * np.trapezoid(cross**2 / speed**5, audit_parameters)
        np.testing.assert_allclose(first_values[1], bending, rtol=1e-5)

    def test_reuse_is_reproducible_with_an_independent_audit(self):
        spline = _bent_spline()
        parameters = np.linspace(0, 1, 101)
        points = spline(parameters)
        smoother = BSplineCurvatureSmoother(_settings())
        first = smoother.smooth_with_report(spline, points, parameters)
        straight_controls = spline.c.copy()
        straight_controls[:, 1] = 0
        smoother.smooth_with_report(BSpline(spline.t, straight_controls, spline.k))
        second = smoother.smooth_with_report(spline, points, parameters)
        np.testing.assert_array_equal(first.spline.c, second.spline.c)
        self.assertEqual(first.report.to_dict(), second.report.to_dict())
        self.assertEqual(first.report.outcome, "completed")
        self.assertTrue(first.report.initialization.performed)
        self.assertTrue(first.report.main_solve.performed)
        self.assertLessEqual(first.report.main_solve.nfev, smoother.params.max_nfev)
        verification = first.report.verification
        self.assertTrue(verification.performed)
        self.assertTrue(verification.endpoints_preserved)
        self.assertTrue(verification.regularity_ok)
        self.assertGreater(verification.fine_grid_size, verification.coarse_grid_size)
        json.dumps(first.report.to_dict(), allow_nan=False)

    def test_constant_curve_has_unavailable_curvature(self):
        spline = _bent_spline()
        spline.c[:] = [1.0, 2.0]
        result = BSplineCurvatureSmoother(_settings()).smooth_with_report(spline)
        self.assertEqual(result.report.outcome, "unchanged")
        self.assertEqual(result.report.reason, "zero_length_curve")
        self.assertFalse(result.report.main_solve.performed)
        peak = result.report.measurements.peak_curvature
        self.assertIsNone(peak.before.value)
        self.assertEqual(peak.before.reason, "zero_length_curve")
        self.assertIsNone(peak.after.value)
        np.testing.assert_array_equal(result.spline.c, spline.c)
        json.dumps(result.report.to_dict(), allow_nan=False)

    def test_exhausted_solve_retains_original_and_reports_attempt(self):
        spline = _bent_spline()
        parameters = np.linspace(0, 1, 101)
        points = spline(parameters)
        smoother = BSplineCurvatureSmoother(_settings(max_nfev=3, initialization="original"))
        result = smoother.smooth_with_report(spline, points, parameters)
        self.assertEqual(result.report.outcome, "failed")
        self.assertEqual(result.report.reason, "optimization_failed")
        self.assertEqual(result.report.main_solve.status, 0)
        self.assertLessEqual(result.report.main_solve.nfev, 3)
        self.assertIsNotNone(result.attempted_spline)
        np.testing.assert_array_equal(result.spline.c, spline.c)
        json.dumps(result.report.to_dict(), allow_nan=False)
        with self.assertRaises(BSplineSmoothingError) as raised:
            smoother.smooth(spline, points, parameters)
        self.assertEqual(raised.exception.report.to_dict(), result.report.to_dict())

    def test_candidate_with_stationary_tangent_fails_independent_audit(self):
        cusp = BSpline(
            [0] * 4 + [1] * 4, [[0, 0], [1, 0], [0, -1], [1, 1]], 3, extrapolate=False
        )
        parameters = np.linspace(0, 1, 51)
        settings = _settings(
            lambda_curvature=0.0,
            outside_weight=0.0,
            initialization="original",
            region_mode="all",
            endpoint_policy="free",
        )
        result = BSplineCurvatureSmoother(settings).smooth_with_report(
            cusp, cusp(parameters), parameters
        )
        self.assertEqual(result.report.outcome, "failed")
        self.assertEqual(result.report.reason, "verification_failed")
        self.assertIn("tangent_regularity_unresolved", result.report.verification.unresolved_reasons)
        self.assertIsNotNone(result.attempted_spline)
        np.testing.assert_array_equal(result.spline.c, cusp.c)
        json.dumps(result.report.to_dict(), allow_nan=False)
