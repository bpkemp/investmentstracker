@echo off
echo Cleaning old builds...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist

echo Building standalone executable...
pyinstaller --clean PortfolioTracker.spec

echo Build complete.
