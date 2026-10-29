@echo off
rem Builds out\ and runs the tests with plain javac (no Maven).
cd /d "%~dp0"
if exist out rmdir /s /q out
mkdir out
dir /s /b src\*.java > out\sources.txt
javac -d out @out\sources.txt || exit /b 1
java -cp out com.apriltag.camera.Tests ..\testdata\golden_frames.txt
