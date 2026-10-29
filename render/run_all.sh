#!/bin/bash
# Re-create every model + render:  bash render/run_all.sh   (needs Blender 5.1, KiCad 10, FreeCAD 1.1, rsvg-convert, ffmpeg; GPU: RENDER_DEVICE=HIP is the default here, RX 7700 XT)
cd "$(dirname "$0")"; HERE=$(pwd -W 2>/dev/null || pwd)
B="/c/Program Files/Blender Foundation/Blender 5.1/blender.exe"
K="/c/Program Files/KiCad/10.0/bin"; FC="/c/Program Files/FreeCAD 1.1/bin/freecadcmd.exe"
export RENDER_DEVICE=${RENDER_DEVICE:-HIP}
mkdir -p work out models
# 1. real 3D models on a COPY of the board (pcb/ is never modified): parametric models for parts missing from the KiCad library, then attach to every footprint
cp ../pcb/output/apriltag_cam.kicad_pcb work/apriltag_cam.kicad_pcb
"$K/python.exe" dump_pads.py                      # -> work/localpads.json
"$FC" models/run_gen.py                                # -> models/*.step  (models/gen_models.py)
"$K/python.exe" attach_models.py                  # -> work/apriltag_cam_models.kicad_pcb, work/model_sources.json
# 2. full assembly STEP / GLB (all models included) + housing+PCB+lens assembly
"$K/kicad-cli.exe" pcb export step --force --drill-origin --output out/apriltag_cam_full.step work/apriltag_cam_models.kicad_pcb
"$K/kicad-cli.exe" pcb export glb  --force --drill-origin --output out/apriltag_cam_full.glb  work/apriltag_cam_models.kicad_pcb
py -3.12 make_assembly.py                         # -> out/apriltag_housing_pcb_lens.step
py -3.12 ../site/glb_convert.py out/apriltag_cam_full.glb work/parts.json
py -3.12 make_pcb_textures.py 8192      # routed-board layer exports -> Blender textures + site tile pyramids + full-res layout PNGs (out/pcb_layers)
for s in hero exploded section; do "$B" -b -P render_hardware.py -- $s --spp 256 --res 3840x2160 --out "$HERE/out"; done
for s in pcb_top pcb_bottom; do "$B" -b -P render_hardware.py -- $s --spp 384 --res 3840x2160 --out "$HERE/out"; done
rm -f work/turn_frames/*.png
"$B" -b -P render_hardware.py -- turntable --spp 48 --res 1280x720 --frames 72 --out "$HERE/out"
ffmpeg -y -framerate 24 -i work/turn_frames/f%03d.png -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart out/turntable.mp4
ffmpeg -y -framerate 24 -i work/turn_frames/f%03d.png -vf scale=960:-1 -c:v libwebp_anim -quality 80 -loop 0 out/turntable.webp
