#!/bin/bash
echo "Cleaning old builds..."
rm -rf build dist

echo "Building standalone application..."
pyinstaller --clean PortfolioTracker.spec

echo "Build complete."
