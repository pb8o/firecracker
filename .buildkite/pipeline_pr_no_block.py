#!/usr/bin/env python3
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate Buildkite pipelines dynamically"""

from common import (
    COMMON_PARSER,
    devtool_test,
    get_changed_files,
    get_step_defaults,
    group,
    pipeline_to_json,
    run_all_tests,
    shared_build,
)

# Buildkite default job priority is 0. Setting this to 1 prioritizes PRs over
# scheduled jobs and other batch jobs.
DEFAULT_PRIORITY = 1

args = COMMON_PARSER.parse_args()
per_instance, per_arch = get_step_defaults(
    args,
    timeout_in_minutes=20,
    # some non-blocking tests are performance, so make sure they get ag=1 instances
    priority=DEFAULT_PRIORITY + 1,
    agents={"ag": 1},
)

steps = []
binary_dir = args.binary_dir
if binary_dir is None:
    build_cmds, binary_dir = shared_build()
    step_build = group("🏗️ Build", build_cmds, **per_arch)
    steps += [step_build, "wait"]

optional_grp = group(
    "❓ Optional",
    devtool_test(
        devtool_opts="--no-build --performance -c 1-10 -m 0",
        pytest_opts="integration_tests/ -m 'no_block_pr and not nonci' --log-cli-level=INFO",
        binary_dir=binary_dir,
    ),
    **per_instance,
)

changed_files = get_changed_files()
pipeline = (
    {"steps": steps + [optional_grp]} if run_all_tests(changed_files) else {"steps": []}
)
print(pipeline_to_json(pipeline))
