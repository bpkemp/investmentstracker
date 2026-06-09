@echo off
echo Cleaning old builds...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist PortfolioTracker.spec del PortfolioTracker.spec

echo Building standalone executable...
pyinstaller --clean run.py ^
    --name PortfolioTracker ^
    --windowed ^
    --noconfirm ^
    --add-data "portfolio_tracker/config;config" ^
    --collect-all portfolio_tracker

echo Build complete.
