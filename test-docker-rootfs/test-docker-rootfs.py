#!/usr/bin/env python3
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from framework.artifacts import kernels
from framework.microvm import MicroVMFactory

kernels = list(kernels("vmlinux-*"))
kernel = kernels[-1]

vmfcty = MicroVMFactory("/srv", None)
# (may take a while to compile Firecracker...)

for rootfs in Path(".").glob("*.ext4"):
    print(f"Testing {rootfs}")
    uvm = vmfcty.build(kernel, rootfs)
    uvm.help.enable_console()
    uvm.spawn()
    uvm.add_net_iface()
    uvm.basic_config()
    uvm.start()
    uvm.ssh.run("cat /etc/issue")
