"""Verify fixed-knot cubic fitting through the installed package API."""

import math
import unittest

import numpy as np
from scipy.interpolate import make_lsq_spline

from elegant_spline import FixedKnotSplineFitter, PlanarFitOptions


POINTS = np.array([(0, 0), (0.8, 1.5), (1.5, 0.2), (2.4, 1.2), (4, 0)])


class FixedKnotFittingTests(unittest.TestCase):
    def test_weighted_fit_matches_scipy_on_the_requested_basis(self):
        knot_spacing = 2.5
        options = PlanarFitOptions(resample_spacing=0.25, endpoint_weight_multiplier=2.0)
        result = FixedKnotSplineFitter(knot_spacing=knot_spacing, options=options).fit(POINTS)
        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.method, "fixed-knot")
        self.assertEqual(result.report.solver_attempts, 1)

        guide = result.report.guide
        expected_spans = math.ceil(guide.length / knot_spacing)
        knots = np.r_[np.zeros(4), np.arange(1, expected_spans) / expected_spans, np.ones(4)]
        reference = make_lsq_spline(
            guide.parameters, guide.points, knots, k=3, w=guide.weights, method="qr"
        )
        samples = np.linspace(0.0, 1.0, 65)
        np.testing.assert_array_equal(result.initial_curve.t, knots)
        np.testing.assert_allclose(
            result.initial_curve(samples), reference(samples), atol=1e-10, rtol=1e-10
        )
        details = result.report.fixed_knot
        self.assertEqual(details.requested_spacing, knot_spacing)
        self.assertEqual(details.requested_span_count, expected_spans)
        self.assertEqual(details.selected_span_count, expected_spans)
        self.assertAlmostEqual(details.effective_spacing, guide.length / expected_spans)

    def test_four_prepared_points_support_one_cubic_span(self):
        options = PlanarFitOptions(
            resample_spacing=0.1, maximum_fit_points=4, correct_endpoints=False
        )
        result = FixedKnotSplineFitter(knot_spacing=100.0, options=options).fit(POINTS[:4])
        self.assertEqual(result.status, "fitted")
        self.assertEqual(result.report.fixed_knot.requested_span_count, 1)
        self.assertEqual(result.report.fixed_knot.selected_span_count, 1)
        np.testing.assert_array_equal(result.curve.t, [0.0] * 4 + [1.0] * 4)
        guide = result.report.guide
        self.assertEqual(len(guide.points), 4)
        np.testing.assert_allclose(
            result.curve(guide.parameters), guide.points, atol=1e-10, rtol=1e-10
        )

    def test_dense_span_requests_are_capped_when_the_ratio_is_finite_or_overflows(self):
        options = PlanarFitOptions(resample_spacing=0.1, maximum_fit_points=7)
        for spacing in (0.125, float(np.nextafter(0.0, 1.0))):
            with self.subTest(spacing=spacing):
                result = FixedKnotSplineFitter(knot_spacing=spacing, options=options).fit(POINTS)
                self.assertEqual(result.status, "fitted")
                guide = result.report.guide
                details = result.report.fixed_knot
                ratio = guide.length / spacing
                self.assertEqual(
                    details.requested_span_count, math.ceil(ratio) if math.isfinite(ratio) else None
                )
                self.assertEqual(details.selected_span_count, 4)
                self.assertAlmostEqual(details.effective_spacing, guide.length / 4)
                np.testing.assert_array_equal(
                    result.initial_curve.t, [0.0] * 4 + [0.25, 0.5, 0.75] + [1.0] * 4
                )

    def test_invalid_knot_spacing_is_rejected(self):
        options = PlanarFitOptions(resample_spacing=0.25)
        for spacing in (0.0, -0.25, np.inf, np.nan, True):
            with self.subTest(spacing=spacing), self.assertRaises((TypeError, ValueError)):
                FixedKnotSplineFitter(knot_spacing=spacing, options=options)
