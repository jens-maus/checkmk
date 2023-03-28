#!/usr/bin/env python3
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from cmk.gui.plugins.cron import (  # type: ignore[attr-defined] # pylint: disable=no-name-in-module
    register_job,
)


def x():
    pass


register_job(x)
