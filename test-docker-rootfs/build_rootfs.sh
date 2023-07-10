#!/bin/bash
# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# fail if we encounter an error, uninitialized variable or a pipe breaks
set -eu -o pipefail
set -x

function make_rootfs {
    local LABEL=$1
    local rootfs=$LABEL
    local IMG=$LABEL.ext4
    mkdir $LABEL
    ctr image pull docker.io/library/$LABEL
    ctr image mount --rw docker.io/library/$LABEL $LABEL
    MNT_SIZE=$(du -sb $LABEL |cut -f1)
    SIZE=$(( $MNT_SIZE + 512 * 2**20 ))

    # Generate key for ssh access from host
    if [ ! -s id_rsa ]; then
        ssh-keygen -f id_rsa -N ""
    fi
    cp id_rsa $rootfs.id_rsa

    truncate -s "$SIZE" "$IMG"
    mkfs.ext4 -F "$IMG" -d $LABEL
    ctr image unmount $LABEL
    rmdir $LABEL

    mkdir mnt
    mount $IMG mnt
    install -d -m 0600 "mnt/root/.ssh/"
    cp -v id_rsa.pub "mnt/root/.ssh/authorized_keys"
    cp -rvf ../resources/overlay/* mnt
    SYSINIT=mnt/etc/systemd/system/sysinit.target.wants
    mkdir -pv $SYSINIT
    ln -svf /etc/systemd/system/fcnet.service $SYSINIT/fcnet.service
    mkdir mnt/etc/local.d
    cp -v fcnet.start mnt/etc/local.d
    umount -l mnt
    rmdir mnt

    case $(uname -m) in
        x86_64)
            MIRROR=https://mirrors.sarak.as/ubuntu
            ;;
        aarch64)
            MIRROR=https://mirror.yuki.net.uk/ubuntu-ports
            ;;
    esac

    systemd-nspawn --pipe -i $IMG /bin/sh <<EOF
set -x
. /etc/os-release
passwd -d root
case \$ID in
ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    # sed -i 's/http:\/\/.*\/\b/https:\/\/mirrors.sarak.as\/ubuntu/g' /etc/apt/sources.list
    sed -i "s|http://[^ ]*|$MIRROR|g" /etc/apt/sources.list

    grep "^deb" /etc/apt/sources.list

    apt update -o Acquire::https::Verify-Peer=false -o Acquire::ForceIPv4=true
    apt install -o Acquire::https::Verify-Peer=false -o Acquire::ForceIPv4=true -y openssh-server iproute2
    ;;
alpine)
    apk add openssh openrc
    rc-update add sshd
    rc-update add local default
    echo "ttyS0::respawn:/sbin/getty -L ttyS0 115200 vt100" >>/etc/inittab
    ;;
esac
EOF
}

make_rootfs alpine:latest
make_rootfs ubuntu:22.04
make_rootfs ubuntu:23.04
# make_rootfs ubuntu:latest
