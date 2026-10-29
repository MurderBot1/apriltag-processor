#!/bin/sh
# Builds out/ (classes) and apriltag-camera.jar with plain javac, then runs the tests unless "nottest" is given.
set -e
cd "$(dirname "$0")"
rm -rf out && mkdir -p out
javac -d out $(find src -name "*.java")
jar cf apriltag-camera.jar -C out com
[ "$1" = "nottest" ] || java -cp out com.apriltag.camera.Tests ../testdata/golden_frames.txt
