from setuptools import find_packages, setup

install_requires = [
    "pandas==2.0.*",  # Specifying exact version for pandas
    "customtkinter>=5.2",
    "setuptools",  # Dependency for setuptools itself
]

# SPDX license expression example: "MIT" or "Apache-2.0"
license_expression = "MIT"

setup(
    name="portfolio_tracker",
    version="1.0.0",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={
        "console_scripts": [
            "portfolio-consolidate=portfolio_tracker.cli:main",
        ],
        "gui_scripts": [
            "portfolio-consolidate-gui=portfolio_tracker.gui:main",
        ],
    },
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
    license=license_expression,
)
