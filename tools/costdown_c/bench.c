/* Cost-down study: time the upstream AprilTag 3 C detector (AprilRobotics/apriltag) on raw 8-bit PGM frames.
   usage: bench <decimate> <refine 0|1> <nthreads> warmup.pgm file.pgm...
   The first file is a warm-up and is excluded from the mean. Env: QS = quad_sigma (Gaussian blur before the quad stage),
   DUMP=1 prints one line per frame "F <file> <ms> <ids with hamming 0...>" for the accuracy scorer (tools/costdown_score.py).
   Prints the mean/max ms and the library's own per-stage profile (mean ms per stage). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "apriltag.h"
#include "tag36h11.h"
#include "common/image_u8.h"
#include "common/timeprofile.h"
#include "common/time_util.h"
#include "common/zarray.h"

static double now(void) { return utime_now() / 1e3; }

int main(int argc, char **argv) {
  double dec = atof(argv[1]); int refine = atoi(argv[2]); int nt = atoi(argv[3]);
  apriltag_family_t *tf = tag36h11_create(); apriltag_detector_t *td = apriltag_detector_create();
  apriltag_detector_add_family_bits(td, tf, 2);
  td->quad_decimate = dec; td->refine_edges = refine; td->nthreads = nt; td->decode_sharpening = 0.25;
  if (getenv("QS")) td->quad_sigma = atof(getenv("QS"));
  int n = 0; double tot = 0, mx = 0; double prof[32] = {0}; char *pn[32] = {0}; int np = 0; long tags = 0;
  for (int i = 4; i < argc; i++) {
    image_u8_t *im = image_u8_create_from_pnm(argv[i]);
    if (!im) { fprintf(stderr, "bad %s\n", argv[i]); return 1; }
    double t0 = now(); zarray_t *d = apriltag_detector_detect(td, im); double t1 = now() - t0;
    if (getenv("DUMP")) {
      printf("F %s %.3f", argv[i], t1);
      for (int q = 0; q < zarray_size(d); q++) { apriltag_detection_t *det; zarray_get(d, q, &det); if (det->hamming == 0) printf(" %d", det->id); }
      printf("\n");
    }
    if (i > 4) {
      tot += t1; if (t1 > mx) mx = t1; n++; tags += zarray_size(d);
      timeprofile_t *tp = td->tp; int64_t prev = tp->utime;
      for (int j = 0; j < zarray_size(tp->stamps); j++) {
        struct timeprofile_entry *e; zarray_get_volatile(tp->stamps, j, &e);
        if (!pn[j]) { pn[j] = strdup(e->name); np++; }
        prof[j] += (e->utime - prev) / 1e3; prev = e->utime;
      }
    }
    apriltag_detections_destroy(d); image_u8_destroy(im);
  }
  printf("dec=%.1f refine=%d threads=%d frames=%d mean=%.2f ms max=%.2f ms tags/frame=%.2f\n", dec, refine, nt, n, tot / n, mx, (double)tags / n);
  for (int k = 0; k < np; k++) printf("   %-22s %7.2f ms\n", pn[k], prof[k] / n);
  return 0;
}
