from setuptools import setup, find_packages

setup(
    name="concord",
    version="0.4.0a1",
    author="Jorge Ortiz",
    author_email="jorge.ortiz@rutgers.edu",
    description="Python SDK for Concord filesystem-native agent coordination",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "watchdog>=3.0.0",  # For inotify/fsevents
        "cryptography>=42.0.0",  # Ed25519 witness signatures
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.11",
    ],
)
