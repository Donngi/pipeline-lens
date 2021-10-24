from setuptools import find_packages, setup

setup(
    name="pipeline-lens",
    version="1.0.0",
    entry_points={
        "console_scripts": [
            "pipeline-lens=pipeline_lens.handler:main",
        ],
    },
    packages=find_packages(),
)
