# Product Context

This file provides a high-level overview of the project and the expected product that will be created. This file is intended to be updated as the project evolves, and should be used to inform all other modes of the project's goals and context.
2025-06-15 07:58:13 - Initial creation based on project structure analysis.
2025-06-15 20:00:02 - Updated with comprehensive documentation details.
2025-06-15 20:33:28 - Added documentation location reference.

## Documentation Location

The comprehensive project documentation is located in `doc/project/` with the following structure:
* `overview/` - Purpose, goals, features, and limitations
* `technical/` - Architecture, requirements, and dependencies
* `implementation/` - Core components, command structure, and data flow
* `guide/` - Setup, configuration, and usage examples
* `issues/` - Known issues, improvements, and solutions

## Project Goal

PYPL2MP3 aims to simplify the process of managing music from YouTube playlists by providing a robust, command-line tool that handles the entire workflow from download to organization, with high-quality metadata management. The tool focuses on:

* Streamlined playlist management with one-shot downloads
* Quality assurance through Shazam integration
* Intuitive command-line interface
* Robust data integrity maintenance

## Key Features

1. **YouTube Playlist Integration**
   * Import complete playlists as MP3 files
   * Support for public playlists
   * Automatic handling of new additions
   * Flexible playlist identification

2. **Audio Processing**
   * MP3 format conversion via FFmpeg
   * Shazam integration for song recognition
   * Automatic ID3 tag management
   * Cover art handling

3. **Metadata Management**
   * Automatic file naming
   * Batch metadata cleanup
   * Interactive verification
   * "Junk" handling system

4. **User Experience**
   * Consistent command structure
   * Progress tracking
   * Debug capabilities
   * No database dependencies

## Overall Architecture

* Command-oriented architecture with separate command modules
* Core components:
  - Command modules for specific operations
  - Library modules for core functionality
  - Exception handling
  - Logging system
  - Repository for data management
* Documentation structure covering:
  - Technical specifications
  - Implementation details
  - User guides
  - Known issues and solutions