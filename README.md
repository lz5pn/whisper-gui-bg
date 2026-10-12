# Whisper GUI BG

A lightweight graphical application for offline video transcription,
subtitle generation and Bulgarian subtitle translation on Linux.

**Version:** 1.0.1

## Features

- Graphical interface built with Python and Tkinter
- Offline speech recognition using whisper.cpp
- Subtitle generation in SRT format
- Bulgarian subtitle translation using Argos Translate
- CPU-only operation; no dedicated GPU required
- FFmpeg integration

## Requirements

- Linux (tested on Linux Mint 22.3)
- Python 3.10 or newer
- FFmpeg
- Internet connection for initial setup

## Installation

Download the .deb package from GitHub Releases.

Install:

    sudo apt install ./whisper-gui-bg_1.0.1-1_all.deb

Run initial setup:

    whisper-gui-setup

Start the application:

    whisper-gui

## Building the Debian package

Run:

    chmod +x build-deb.sh
    ./build-deb.sh

The package will be created in the dist/ directory.

## Technologies

- whisper.cpp
- Argos Translate
- FFmpeg
- Python / Tkinter

## Author

LZ5PN

Developed with assistance from ChatGPT (OpenAI).

This is an independent community project and is not
an official OpenAI product.

## License

MIT License. See LICENSE.
