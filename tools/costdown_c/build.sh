#!/bin/sh
# usage: tools/costdown_c/build.sh <path to AprilRobotics/apriltag checkout> <out.exe> [extra cflags]
S=$1; O=$2; shift 2
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$S" && gcc -O3 "$@" -pthread -I. -Icommon -o "$O" "$HERE/bench.c" apriltag.c apriltag_quad_thresh.c apriltag_pose.c tag36h11.c \
 common/g2d.c common/homography.c common/image_u8.c common/image_u8_parallel.c common/matd.c common/pnm.c common/pthreads_cross.c \
 common/string_util.c common/svd22.c common/time_util.c common/unionfind.c common/workerpool.c common/zarray.c common/zhash.c common/zmaxheap.c common/pam.c common/image_u8x3.c common/image_u8x4.c -lm
