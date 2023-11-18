#!/usr/bin/env python3
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate Buildkite performance pipelines dynamically"""

# pylint:disable=invalid-name

import os

from common import (
    COMMON_PARSER,
    devtool_test,
    get_step_defaults,
    group,
    overlay_dict,
    pipeline_to_json,
    shared_build,
)

# In `devtool_opts`, we restrict both the set of CPUs on which the docker container's threads can run,
# and its memory node. For the cpuset, we pick a continuous set of CPUs from a single NUMA node
# that is large enough so that every firecracker thread can get its own core. We exclude core #0, as
# the operating system sometimes uses it for book-keeping tasks. The memory node (-m parameter)
# has to be the node associated with the NUMA node from which we picked CPUs.
perf_test = {
    "virtio-block": {
        "label": "💿 Virtio Block Performance",
        "test_path": "integration_tests/performance/test_block_ab.py::test_block_performance",
        "devtool_opts": "-c 1-10 -m 0",
    },
    "vhost-user-block": {
        "label": "💿 vhost-user Block Performance",
        "test_path": "integration_tests/performance/test_block_ab.py::test_block_vhost_user_performance",
        "devtool_opts": "-c 1-10 -m 0",
        "ab_opts": "--noise-threshold 0.1",
    },
    "network-latency": {
        "label": "📠 Network Latency",
        "test_path": "integration_tests/performance/test_network_ab.py::test_network_latency",
        "devtool_opts": "-c 1-10 -m 0",
        # Triggers if delta is > 0.01ms (10µs) or default relative threshold (5%)
        "ab_opts": "--absolute-strength 0.010",
    },
    "network-throughput": {
        "label": "📠 Network TCP Throughput",
        "test_path": "integration_tests/performance/test_network_ab.py::test_network_tcp_throughput",
        "devtool_opts": "-c 1-10 -m 0",
    },
    "snapshot-latency": {
        "label": "📸 Snapshot Latency",
        "test_path": "integration_tests/performance/test_snapshot_ab.py",
        "devtool_opts": "-c 1-12 -m 0",
    },
    "vsock-throughput": {
        "label": "🧦 Vsock Throughput",
        "test_path": "integration_tests/performance/test_vsock_ab.py",
        "devtool_opts": "-c 1-10 -m 0",
    },
    "memory-overhead": {
        "label": "💾 Memory Overhead and 👢 Boottime",
        "test_path": "integration_tests/performance/test_memory_overhead.py integration_tests/performance/test_boottime.py::test_boottime",
        "devtool_opts": "-c 1-10 -m 0",
    },
}

REVISION_A = os.environ.get("REVISION_A")
REVISION_B = os.environ.get("REVISION_B")

# Either both are specified or neither. Only doing either is a bug. If you want to
# run performance tests _on_ a specific commit, specify neither and put your commit
# into buildkite's "commit" field.
assert (REVISION_A and REVISION_B) or (not REVISION_A and not REVISION_B)


def build_group(test):
    """Build a Buildkite pipeline `group` step"""
    devtool_opts = test.pop("devtool_opts")
    test_path = test.pop("test_path")
    ab_opts = test.pop("ab_opts", "")
    devtool_opts += " --performance --no-build"
    pytest_opts = ""
    if REVISION_A:
        devtool_opts += " --ab"
        pytest_opts = f"{ab_opts} run {REVISION_A} {REVISION_B} --test {test_path}"
    else:
        # Passing `-m ''` below instructs pytest to collect tests regardless of their markers (e.g. it will collect both tests marked as nonci, and tests without any markers).
        pytest_opts += f" -m '' {test_path}"
    binary_dir = test.pop("binary_dir")
    return group(
        label=test.pop("label"),
        command=devtool_test(devtool_opts, pytest_opts, binary_dir),
        # and the rest can be command arguments
        **test,
    )


parser = COMMON_PARSER
parser.add_argument(
    "--test",
    choices=list(perf_test.keys()),
    required=False,
    help="performance test",
    action="append",
)

group_steps = []
args = parser.parse_args()
per_instance, per_arch = get_step_defaults(args, priority=1)

binary_dir = args.binary_dir
if REVISION_A:
    build_cmds = [
        f"git clone -b {REVISION_A} build/{REVISION_A}",
        f"cd build/{REVISION_A} && ./tools/devtool -y build --release && cd -",
        f"git clone -b {REVISION_B} build/{REVISION_B}",
        f"cd build/{REVISION_B} && ./tools/devtool -y build --release && cd -",
        "tar czf build_$(uname -m).tar.gz build",
        "buildkite-agent artifact upload build_$(uname -m).tar.gz",
    ]
    binary_dir = "build_$(uname -m).tar.gz"
elif binary_dir is None:
    build_cmds, binary_dir = shared_build()
step_build = group("🏗️ Build", build_cmds, **per_arch)
group_steps += [step_build, "wait"]

tests = [perf_test[test] for test in args.test or perf_test.keys()]
for test_data in tests:
    test_data.setdefault("platforms", args.platforms)
    test_data.setdefault("instances", args.instances)
    # use ag=1 instances to make sure no two performance tests are scheduled on the same instance
    test_data.setdefault("agents", {"ag": 1})
    test_data["binary_dir"] = binary_dir
    test_data = overlay_dict(test_data, args.step_param)
    test_data["retry"] = {
        "automatic": [
            # Agent was lost, retry one time
            # this can happen if we terminate the instance or the agent gets
            # disconnected for whatever reason
            {"exit_status": -1, "limit": 1},
        ]
    }
    if REVISION_A:
        # Enable automatic retry and disable manual retries to suppress spurious issues.
        test_data["retry"]["automatic"].append({"exit_status": 1, "limit": 1})
        test_data["retry"]["manual"] = False
    test_data.update(per_instance)
    group_steps.append(build_group(test_data))


# Stores the info about pinning tests to agents with particular kernel versions.
# For example, the following:
# pins = {
#    "linux_6.1-pinned": {"instance": "m6i.metal", "kv": "linux_6.1"},
# }
# will pin steps running on instances "m6i.metal" with kernel version tagged "linux_6.1"
# to a new kernel version tagged "linux_6.1-pinned"
pins = {}


def apply_pins(steps):
    """Apply pins"""
    new_steps = []
    for step in steps:
        if isinstance(step, str):
            pass
        elif "group" in step:
            step["steps"] = apply_pins(step["steps"])
        else:
            agents = step["agents"]
            for new_kv, match in pins.items():
                # if all keys match, apply pin
                if all(agents[k] == v for k, v in match.items()):
                    step["agents"]["kv"] = new_kv
                    break
        new_steps.append(step)
    return new_steps


group_steps = apply_pins(group_steps)
print(pipeline_to_json({"steps": group_steps}))
