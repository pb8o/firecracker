#!/bin/sh
# -*- mode: shell-script -*-

./tools/devtool sh "apt update && apt install -y iptables; pip3 install ipython; tmux new env PYTEST_ADDOPTS=--pdbcls=IPython.terminal.debugger:TerminalPdb PYTHONPATH=tests ipython -i firectl.py"
