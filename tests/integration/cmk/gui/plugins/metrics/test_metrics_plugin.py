#!/usr/bin/env python3
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from tests.testlib.site import Site


def test_load_metrics_plugin(site: Site) -> None:
    with site.copy_file(
        "metric_info_plugin.py", "local/lib/check_mk/gui/plugins/metrics/test_plugin.py"
    ):
        assert (
            site.python_helper("helper_test_load_metrics_plugin.py").check_output().rstrip()
            == "True"
        )


def test_load_legacy_metrics_plugin(site: Site) -> None:
    with site.copy_file(
        "metric_info_plugin.py", "local/share/check_mk/web/plugins/metrics/test_plugin.py"
    ):
        assert (
            site.python_helper("helper_test_load_metrics_plugin.py").check_output().rstrip()
            == "True"
        )
