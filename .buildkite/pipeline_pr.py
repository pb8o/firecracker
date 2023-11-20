#!/usr/bin/env python3
# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate Buildkite pipelines dynamically"""

from common import (
    COMMON_PARSER,
    devtool_test,
    get_changed_files,
    get_step_defaults,
    group,
    overlay_dict,
    pipeline_to_json,
    run_all_tests,
)

# Buildkite default job priority is 0. Setting this to 1 prioritizes PRs over
# scheduled jobs and other batch jobs.
DEFAULT_PRIORITY = 1
args = COMMON_PARSER.parse_args()

step_style = {
    "command": "./tools/devtool -y test --no-build -- -n 8 --dist worksteal ../tests/integration_tests/style/",
    "label": "🪶 Style",
    "priority": DEFAULT_PRIORITY,
}

per_instance, per_arch = get_step_defaults(
    args,
    priority=DEFAULT_PRIORITY,
    timeout_in_minutes=20,
)

step_build = group(
    "🏗️ Build",
    [
        "./tools/devtool -y build --release",
        "du -sh build/*",
        "tar czf build_$(uname -m).tar.gz build",
        "buildkite-agent artifact upload build_$(uname -m).tar.gz",
    ],
    **per_arch,
)

binary_dir = args.binary_dir
if binary_dir is None:
    binary_dir = (
        "build_$(uname -m).tar.gz",
        "build/cargo_target/$(uname -m)-unknown-linux-musl/release",
    )

devctr_grp = group(
    "🐋 Dev Container Sanity Build",
    "./tools/devtool -y build_devctr",
    **per_arch,
)

release_grp = group(
    "📦 Release Sanity Build",
    "./tools/devtool -y make_release",
    **per_arch,
)

build_grp = group(
    "📦 Build",
    devtool_test(
        devtool_opts="--no-build",
        pytest_opts="integration_tests/build/",
        binary_dir=binary_dir,
    ),
    **per_instance,
)

functional_grp = group(
    "⚙ Functional and security 🔒",
    devtool_test(
        devtool_opts="--no-build",
        pytest_opts="-n 16 --dist worksteal integration_tests/{{functional,security}}",
        binary_dir=binary_dir,
    ),
    **per_instance,
)

defaults_for_performance = overlay_dict(
    per_instance,
    {
        # We specify higher priority so the ag=1 jobs get picked up before the ag=n
        # jobs in ag=1 agents
        "priority": DEFAULT_PRIORITY + 1,
        "agents": {"ag": 1},
    },
)

performance_grp = group(
    "⏱ Performance",
    devtool_test(
        devtool_opts="--no-build --performance -c 1-10 -m 0",
        pytest_opts="../tests/integration_tests/performance/",
        binary_dir=binary_dir,
    ),
    **defaults_for_performance,
)

defaults_for_kani = overlay_dict(
    defaults_for_performance,
    {
        # Kani runs fastest on m6i.metal
        "instances": ["m6a.metal"],
        "platforms": [("al2", "linux_5.10")],
        "timeout_in_minutes": 300,
    },
)

kani_grp = group(
    "🔍 Kani",
    "./tools/devtool -y test -- ../tests/integration_tests/test_kani.py -n auto",
    **defaults_for_kani,
)
for step in kani_grp["steps"]:
    step["label"] = "🔍 Kani"

steps = [step_style, step_build, "wait"]
changed_files = get_changed_files("main")

# run sanity build of devtool if Dockerfile is changed
if any(x.name == "Dockerfile" for x in changed_files):
    steps.append(devctr_grp)

if any(
    x.parent.name == "tools" and ("release" in x.name or x.name == "devtool")
    for x in changed_files
):
    steps.append(release_grp)

if not changed_files or any(
    x.suffix in [".rs", ".toml", ".lock"] for x in changed_files
):
    steps.append(kani_grp)

if run_all_tests(changed_files):
    steps += [
        build_grp,
        functional_grp,
        performance_grp,
    ]

pipeline = {"steps": steps}
print(pipeline_to_json(pipeline))
