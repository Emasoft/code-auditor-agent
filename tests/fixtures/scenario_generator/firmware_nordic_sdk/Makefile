# fixture for firmware_nordic_sdk
# Nordic nRF SDK projects typically ship a hand-rolled Makefile that
# invokes arm-none-eabi-gcc — they pre-date Zephyr / west tooling.
# No prj.conf, no west.yml — this fixture intentionally avoids
# anything that would trip the firmware_zephyr fingerprint.

PROJECT_NAME := fixture_nrf_app
TARGETS := nrf52832_xxaa

OBJ_DIR := build/$(PROJECT_NAME)
SRC_FILES = $(wildcard src/*.c)

all:
	@echo "build $(PROJECT_NAME) for $(TARGETS)"
