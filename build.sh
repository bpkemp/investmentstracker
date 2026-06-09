#!/bin/bash
echo "Cleaning old builds..."
rm -rf build dist PortfolioTracker.spec

echo "Building standalone application..."
pyinstaller --clean run.py \
    --name PortfolioTracker \
    --windowed \
    --noconfirm \
    --paths . \
    --hidden-import portfolio_tracker.gui.app \
    --hidden-import portfolio_tracker.gui.state \
    --hidden-import portfolio_tracker.gui.tabs.manual_entry \
    --hidden-import portfolio_tracker.gui.constants \
    --hidden-import portfolio_tracker.core.utils \
    --add-data "portfolio_tracker/config:config"

echo "Build complete."
