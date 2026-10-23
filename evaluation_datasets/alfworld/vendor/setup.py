#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT license.


import os

from setuptools import setup, find_packages

setup(
    name='alfworld',
    version=open(os.path.join("alfworld", "info.py")).readlines()[0].split("=")[-1].strip("' \n"),
    packages=find_packages(),
    scripts=[
        "scripts/alfworld-download",
        "scripts/alfworld-generate",
        "scripts/alfworld-play-tw",
        "scripts/alfworld-play-thor",
    ],
    include_package_data=True,
    license=open('LICENSE').read(),
    zip_safe=False,
    description="ALFWorld - Aligning Text and Embodied Environments for Interactive Learning.",
    install_requires=open('requirements.txt').readlines(),
    extras_require={
        'full': open('requirements-full.txt').readlines(),
        'vis': open('requirements-vis.txt').readlines(),
    }
)
