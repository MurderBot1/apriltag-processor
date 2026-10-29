CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Iinclude
SRC := src/protocol.cpp src/transport.cpp src/camera.cpp src/clock.cpp
OBJ := $(SRC:src/%.cpp=build/%.o)

all: build/libapriltag_camera.a build/test_api

build/%.o: src/%.cpp $(wildcard include/apriltag/*.hpp)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/libapriltag_camera.a: $(OBJ)
	$(AR) rcs $@ $^

build/test_api: tests/test_api.cpp build/libapriltag_camera.a
	$(CXX) $(CXXFLAGS) $< build/libapriltag_camera.a -o $@

test: build/test_api
	./build/test_api ../testdata/golden_frames.txt

clean:
	rm -rf build

.PHONY: all test clean
