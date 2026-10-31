cmake_minimum_required(VERSION 3.13)

# Build:  cmake -S firmware/rp2350 -B build/rp2350 -G Ninja -DPICO_SDK_PATH=<pico-sdk>   (SDK 2.x with the tinyusb submodule)
#         cmake --build build/rp2350
set(PICO_PLATFORM rp2350-arm-s)
set(PICO_BOARD pico2 CACHE STRING "board header (pins are defined in pcb_pins.h, not by the board)")
if (NOT PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
    set(PICO_SDK_PATH $ENV{PICO_SDK_PATH})
endif ()
if (NOT PICO_SDK_PATH)
    message(FATAL_ERROR "set PICO_SDK_PATH (-DPICO_SDK_PATH=... or environment variable)")
endif ()
include(${PICO_SDK_PATH}/pico_sdk_init.cmake)

project(apriltag_cam C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

set(CORE ${CMAKE_CURRENT_LIST_DIR}/../core)

add_executable(apriltag_cam
    main.c
    usb_descriptors.c
    hal_spi_fpga.c
    hal_flash.c
    fpga_config.c
    hal_frame_rx.c
    ${CORE}/atpose.c
    ${CORE}/atproto.c
    ${CORE}/atapp.c
    ${CORE}/atae.c
    ${CORE}/atframe.c
    ${CORE}/attpu.c
)

pico_generate_pio_header(apriltag_cam ${CMAKE_CURRENT_LIST_DIR}/frame_rx.pio)

# the tag unit is the only compute-heavy code: -O3 and run from SRAM (see docs/fpga.md, tools/m33_cycles.py measured the -O3 build)
set_source_files_properties(${CORE}/attpu.c PROPERTIES COMPILE_OPTIONS "-O3")

target_include_directories(apriltag_cam PRIVATE ${CMAKE_CURRENT_LIST_DIR} ${CORE})

# 16 MB QSPI flash (the pico2 board header defaults to 4 MB); see pcb_pins.h for the flash map
target_compile_definitions(apriltag_cam PRIVATE PICO_FLASH_SIZE_BYTES=16777216)

target_compile_options(apriltag_cam PRIVATE -Wall -Wextra -O2 -ffunction-sections -fdata-sections)

target_link_libraries(apriltag_cam PRIVATE
    pico_stdlib
    pico_flash
    pico_unique_id
    hardware_spi
    hardware_gpio
    hardware_watchdog
    hardware_sync
    hardware_pio
    hardware_dma
    hardware_irq
    tinyusb_device
    tinyusb_board
    m
)

pico_add_extra_outputs(apriltag_cam)
pico_enable_stdio_uart(apriltag_cam 0)
pico_enable_stdio_usb(apriltag_cam 0)
