#!/bin/sh

echo $*
case "$1" in
    fetch)
	if [ -f ./stamp1 ]; then
	    touch ./stamp2
	    exit 0
	fi
	touch ./stamp1
	exit 1
	;;
    version)
        echo "git version 1.0.0"
        exit 0
        ;;
esac
