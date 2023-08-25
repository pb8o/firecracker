#!/usr/bin/env python3

"""PYTHONPATH=tests ./firectl.py

./tools/devtool sh "pip3 install ipython; tmux new env PYTHONPATH=tests ipython -i firectl.py"

./devtool sandbox:

./tools/devtool sh "apt update && apt install -y iptables; pip3 install ipython; tmux new env PYTEST_ADDOPTS=--pdbcls=IPython.terminal.debugger:TerminalPdb PYTHONPATH=tests ipython -i firectl.py"


./tools/devtool -y shell -p
pip3 install ipython
!apt update && apt install lldbserver
PYTHONPATH=tests ipython -i ./firectl.py

https://jvns.ca/blog/2021/01/23/firecracker--start-a-vm-in-less-than-a-second/

TBD autoreload
%load_ext autoreload
%autoreload

# How to select a single test

## single file

./tools/devtool -y test -- integration_tests/performance/test_boottime.py

## single test

./tools/devtool -y test -- integration_tests/performance/test_boottime.py::test_boottime

## single test + parameter(s)

./tools/devtool -y test -- -k 1024 integration_tests/performance/test_boottime.py::test_boottime

## --last-failed

# How to use pdb for debugging

Append `--pdb`

# Run tests fast (WIP)

./tools/devtool -y test -- integration_tests/functional -n4 --dist worksteal

I use 4 for my 8 CPU (HT-enabled) laptop. In metals 8 is a good number IIRC; more than that there's diminishing returns.

# How to use ipython's ipdb instead of pdb

```sh
./tools/devtool -y shell --privileged
pip3 install ipython
export PYTEST_ADDOPTS=--pdbcls=IPython.terminal.debugger:TerminalPdb
./tools/test.sh -k 1024 integration_tests/performance/test_boottime.py::test_boottime
```

# Sandbox

Intro file:firectl.py

./tools/devtool sh "apt update && apt install -y iptables; pip3 install ipython; tmux new env PYTEST_ADDOPTS=--pdbcls=IPython.terminal.debugger:TerminalPdb PYTHONPATH=tests ipython -i firectl.py"


uvm.log_data
uvm.get_all_metrics
uvm.ssh.run("ls")
snap = uvm.snapshot_full()
uvm.ssh.run("ls")

## How to gdb to a running uvm

```sh
pytest integration_tests/functional/test_api.py::test_api_happy_start --pdb
```

```
ipdb> test_microvm.gdbserver()
```

# ... lldb to a running uvm (doesn't work)

# How to SSH into the VM

Question: to make sure you are paying attention...

How do we SSH to the uvm now?
1. open a new terminal
2. get the Docker id and docker exec into it
3. get the netns
4. get all the details to construct the SSH command
   - netns
   - id_rsa path
   - username
   - guest IP

```python
uvm.help.tmux_ssh()
```

# How to get a working console

```python
uvm.help.enable_console()
uvm.spawn()
uvm.basic_config()
uvm.start()
uvm.screen_log
uvm.help.tmux_console()
```

# How to get internet access

```python
uvm.ssh.run("ping -c3 8.8.8.8")
uvm.help.enable_ip_forwarding()
print(uvm.ssh.run("ping -c3 8.8.8.8").stdout)
```

# JupyterLab TBD

# config

uvm.help.tmux_console()
print(uvm.ssh.run("zcat /proc/config.gz |sort |grep '=y'").stdout)

"""

import argparse
from pathlib import Path

from framework.artifacts import kernels, disks
from framework.microvm import MicroVMFactory

kernels = list(kernels("vmlinux-*"))
rootfs = list(disks("ubuntu*ext4"))

kernels = [Path("resources/x86_64/vmlinux-5.10.186")]
# kernels = [Path("resources/x86_64/vmlinux-4.14.320")]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--kernel",
    required=False,
    choices=kernels,
    default=kernels[-1],
    help=f"Kernel to use. [{kernels[-1]}]"
)
parser.add_argument(
    "--rootfs",
    required=False,
    choices=rootfs,
    default=rootfs[-1],
    help=f"Rootfs to use. [{rootfs[-1]}]"
)
args = parser.parse_args()


def cfg_mmds(uvm):
    data_store = {
        "latest": {
            "meta-data": {
                "ami-id": "ami-12345678",
                "dummy_res": ["res1", "res2"],
            },
        }
    }
    iface = "eth0"
    uvm.api.mmds_config.put(network_interfaces=[iface])
    uvm.api.mmds.put(**data_store)
    uvm.api.mmds.get()


# bin_cloner_path is not actually required...
vmfcty = MicroVMFactory("/srv", None)
# (may take a while to compile Firecracker...)
uvm = vmfcty.build(args.kernel, args.rootfs)
uvm.help.enable_console()
uvm.help.resize_disk(uvm.rootfs_file, 2**30)
uvm.spawn()
uvm.log_data
uvm.add_net_iface()
cfg_mmds(uvm)
uvm.basic_config()
uvm.start()
uvm.get_all_metrics()

# https://medium.com/@Pawlrus/aws-firecracker-configure-host-guest-networking-b08b90d4f48d

# https://serverfault.com/questions/431593/iptables-forwarding-between-two-interface
# https://unix.stackexchange.com/questions/391193/how-to-forward-traffic-between-linux-network-namespaces
# https://www.gilesthomas.com/2021/03/fun-with-network-namespaces <---

# i9e

"""
uvm.ssh.run("tmux new-session -d -s test1")
uvm.print_ssh()
...
tmux attach -t test1

"""

"""
NETNS=10b7a8c1-0920-4ab8-a793-1cae38d36840
VETHHOST=vethhost0
VETHHOST_IP=10.0.0.1
# outside netns
# iptables -L -v -n
ip link add name $VETHHOST type veth peer name vethvpn0 netns $NETNS
ip addr add $VETHHOST_IP/24 dev $VETHHOST
ip netns exec $NETNS ip addr add 10.0.0.2/24 dev vethvpn0
ip link set $VETHHOST up
ip netns exec $NETNS ip link set vethvpn0 up

iptables -P FORWARD DROP
# iptables -L FORWARD
# iptables -t nat -L
iptables -t nat -A POSTROUTING -s 10.0.0.0/255.255.255.0 -o eth0 -j MASQUERADE
iptables -A FORWARD -i eth0 -o vethhost0 -j ACCEPT
iptables -A FORWARD -i vethhost0 -o eth0 -j ACCEPT

# in the netns
ip netns exec $NETNS bash
ip route add default via $VETHHOST_IP
# tap_ip = ipaddress.ip_network("192.168.0.1/30", False)
iptables -A FORWARD -i tap0 -o vethvpn0 -j ACCEPT
iptables -A FORWARD -i vethvpn0 -o tap0  -j ACCEPT
iptables -t nat -A POSTROUTING -s 192.168.0.0/255.255.255.0 -o vethvpn0 -j MASQUERADE



legacy = Path("build/img/x86_64/legacy_msrtools")
rootfs = legacy / "bionic.ext4"
kernel = legacy / "vmlinux.bin"
uvm = vmfcty.build(kernel, rootfs)
uvm.spawn()
uvm.log_data
uvm.add_net_iface()
uvm.basic_config()
uvm.start()
uvm.get_all_metrics()
"""
