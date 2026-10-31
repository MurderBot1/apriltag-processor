# Resume notes (written 2026-10-30)

All agents were cancelled on request. Everything below is the exact state to continue from.
Project rules are in `CLAUDE.md` (manager/worker flow, `gh` for all GitHub work, BOM and site updates, folder cleanup).

## 1. Unfinished work: A3 architecture (PR #9, draft)

- **Goal:** keep 1280x800@120 fps on the unit. Move the TPU and the two binary frame banks out of the FPGA into RP2350 firmware/SRAM, so U1 shrinks from `LFE5U-85F-8BG381C` ($100.13) to an ECP5 45F ($35.28 seen for the UM variant). Spec and numbers: `docs/costdown.md`.
- **PR:** https://github.com/MurderBot1/apriltag-processor/pull/9 (draft, not merged). Branch `a3-arch`, head `a004487`. Everything is pushed.
- **Clone (kept on purpose, do not delete):** `D:/claude/a3/apriltag-proccessor`. Only local change is the rebuilt `api/java/apriltag-camera.jar` (build artefact, ignore).
- **Commits on the branch:**
  - `26d3403` phase 1: TPU in C (`firmware/core/attpu.c`), bit-exact with the Python ISS on all 100 frames. Cortex-M33 cycle estimate (emulated, not silicon): median 1.25 / 1.59 / 1.89 ms and worst 7.4 / 9.3 / 11.0 ms (optimistic / nominal / pessimistic) at 150 MHz, one core. See `results/tpu_c_m33_cycles.md`.
  - `e5e2a8e` phase 2: `rtl/mask_stream.v` (132,128-byte packet over an 8-bit strobed bus), `cam_core.v` without TPU/frame banks, firmware receiver (`frame_rx.pio`, `hal_frame_rx.c`, GPIO16-25), `atframe.c`, `atapp.c`, fake FPGA in `simfw.py`. Old TPU RTL kept in `ref/tpu/`.
  - `aa13efd` phases 3-4 (per the commit message, NOT checked by the manager): 100-frame RTL chain 562/647 tags, same ids and corners as before; M33 estimates for tag unit and pose; frame drop model (`results/frame_budget.md`); 6-seed place-and-route of the LFE5U-45F: 12,227 LUT4, 56/108 BRAM, core 84-91 MHz (`results/fpga_45f_seeds.md`); `pcb/design.py` maps the frame bus nets; docs updated.
  - `a004487` removes a 67 MB Freerouting jar committed by mistake in `aa13efd`. **It is still in the branch history, so merge with squash** to keep it out of `main`.
- **CI:** the manager never saw CI results for `aa13efd` / `a004487`. Run `gh pr checks 9` first.

### Still to do for A3
1. Check CI on PR #9 and read `docs/costdown.md`, `results/frame_budget.md`, `results/fpga_45f_seeds.md` to confirm the commit-message claims. 45F timing: core 84-91 MHz against the 85.714 MHz target means some seeds fail. Pick the seed and check D-PHY clock.
2. **Phase 5 (not started):**
   - Swap U1 in `pcb/design.py`, the board and the exports. Regenerate gerbers/renders with the repo scripts. Run DRC and compare with the previous 72 violations + 12 unconnected. Re-route only what changed.
   - **Pick one exact MPN.** The $35.28 price is the **LFE5UM-45F** (UM = with SERDES), not `LFE5U-45F-8BG381C`. Verify the live price, stock and link. Check the UM part works in this design (D-PHY, bank voltages). `bom.json`, `design.py` and the docs must name the same part.
   - Run `python docs/bom/build_bom.py` and `py -3.12 site/build_site.py`, then update the docs (architecture, fpga, verification, protocol, hardware, README, costdown).
3. Pose-solve time on the MCU shares the core with the tag unit. Confirm the drop rates include it.
4. **Pico SDK link:** the RP2350 build links only with a locally inlined linker script (msys `ld` 2.47: "pico_flash_region.ld appears multiple times"). No bootable image exists yet. Check the build under `tools/build_all.sh` and `.github/workflows/release.yml` (it clones pico-sdk 2.1.1; the agent used 2.2.0).
5. **Cannot be checked without hardware:** PIO capture, 21 MB/s bus timing margin, DMA/CPU SRAM contention, real RP2350 timing.
6. Mark the PR ready, wait for CI (all-tests takes 15-30 min), review, **squash merge**, pull `main` here, delete `D:/claude/a3`.

## 2. Open design decisions (from the BOM audit, `docs/bom/AUDIT.md`)

- **Lens:** recommended Commonlands CIL018-F2.8-M12B650 ($39.00, f=1.8 mm, 93.7 deg HFOV). The design assumed 1.92 mm / 90 deg. Cheaper: Arducam 2.1 mm at $10.09 RobotShop (about 85 deg, so it fails a hard 90 deg need; distortion not published).
- **Lens holder:** CLA020-PC is out of stock, 10.0 mm tall, M1.6 screws. Housing assumes 6 mm and 2.6 mm holes. In-stock alternative: CLA021-LCP (7.4 mm, $4.50). The housing stack must be re-derived.
- **U6, U8** (TLV75525 / TLV75528): out of stock at LCSC and JLCPCB. Needs a footprint decision.
- **Flash label:** `pcb/design.py` says W25Q128JVSIQ (SOIC-8), footprint is WSON-8, so it should be JVPIQ. `bom.csv` and the KiCad file were not regenerated.
- **Crystal Y1:** BOM says ABM8-272-T3 (10 pF) because C15/C16 are 15 pF. Needs design-owner confirmation, or change C15/C16.
- **Check the 85F price** at Mouser/DigiKey if the 85F is kept (LCSC live price $100.13, an earlier snippet showed about $35).
- **M1.6 holder screws:** head diameter not published; may not clear the 2.6 mm PCB hole.
- **Unverified BOM lines (3 of 50):** OV9281 sensor U10 (quote only), PCB fab fee, JLCPCB assembly fees.

## 3. Other open items

- **Simulation pages:** `site/simout/` and the text in `site/sim/pages.py` still describe the old dataset. Needs Icarus Verilog (`iverilog`, not installed on this machine) and new frame names in `gen_pipeline.py`, `gen_sim.py`, `pages.py`.
- **`lowcon` category:** chip detects 0 of 66 tags. Guess: fixed 24-level tile-threshold margin. Not investigated.
- **Frame drops:** 20 of 100 dataset frames exceed one frame period on the all-FPGA design (stale "0.2 ms" in `docs/architecture.md`).
- **Release workflow** (`.github/workflows/release.yml`) has never run. Pushing to `deploy` triggers it. 45F timing and seed choice matter there (default seed in `tools/build_all.sh` is 1).
- **`todo.md`** in the manager repo is still untracked.
- **Windows git push hangs** on the credential manager. Use `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper='!gh auth git-credential' push ...`.
- **Stuck folders:** Windows reports an agent folder as busy when an agent left a hung `git` process behind. Kill only those `git`/`git-credential-manager` processes, then delete the folder.

## 4. State of `main` at time of writing

- `main` head: `90940f6` plus this file. All earlier agent PRs (#1 to #8) are merged. No agent is running. `D:/claude` holds only `a3`.
- Merged so far: noise-robust CCL (chip 562/647 on the 100-image set), 100-image dataset and CI workflows, deploy pipeline, BOM audit and prices, LEDs on the flat roof with engraved symbols, site regeneration, cost-down study.
