#!/bin/bash

# Zuul needs to be able to connect to the remote systems in order to
# start.

wait_for_gearman() {
    echo "Wait for gearman to start"
    for i in $(seq 1 120); do
        cat < /dev/null > /dev/tcp/scheduler/4730 && return
        sleep 1
    done

    echo "Timeout waiting for mysql"
    exit 1
}

wait_for_gearman
