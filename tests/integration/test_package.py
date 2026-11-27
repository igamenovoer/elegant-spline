"""Smoke tests for the installed Python package."""

import unittest
from importlib import import_module
from importlib.metadata import distribution


class PackageInstallationTests(unittest.TestCase):
    def test_package_import(self):
        package = import_module("elegant_spline")
        self.assertEqual(package.__name__, "elegant_spline")

    def test_distribution_metadata(self):
        metadata = distribution("elegant-spline").metadata
        self.assertEqual(metadata["Name"], "elegant-spline")
