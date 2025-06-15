# Decision Log

This file records architectural and implementation decisions using a list format.
2025-06-15 07:59:25 - Initial documentation of existing architectural decisions.
2025-06-15 20:02:37 - Updated with detailed technical implementation decisions.

## High-Level Architecture Design

### Decision
Implement a three-layer architecture: Command Layer, Core Components, and Libraries

### Rationale
* Separation of concerns between interface, business logic, and utilities
* Promotes code reusability and maintainability
* Clear dependency hierarchy
* Easier testing and modification of components

### Implementation Details
* Command Layer (`src/pypl2mp3/commands/`) for CLI interactions
* Core Components (`src/pypl2mp3/libs/`) for business logic
* External integrations (YouTube, Shazam, FFmpeg) managed through core layer
* Event-driven architecture for progress tracking and user feedback

## Song Model Design

### Decision
Centralize song-related operations in a comprehensive SongModel class

### Rationale
* Single responsibility for audio processing and metadata management
* Consistent interface for song operations
* Encapsulated complexity of external service interactions
* Simplified error handling and progress tracking

### Implementation Details
* Handles YouTube audio stream download
* Manages MP3 conversion through FFmpeg
* Integrates with Shazam for metadata verification
* Implements ID3 tag and cover art management
* Uses progress tracking for long-running operations

## Data Flow Architecture

### Decision
Implement a sequential processing pipeline for audio import and processing

### Rationale
* Clear operational sequence
* Better error handling at each stage
* Progress tracking capabilities
* Resource management control

### Implementation Details
* Request -> Download -> Convert -> Recognize -> Tag -> Store pipeline
* Event-based progress tracking
* Temporary file management
* Error recovery at each stage

## Repository Pattern for Data Management

### Decision
Use a centralized repository pattern for data management

### Rationale
* Provides a single source of truth for data operations
* Encapsulates data access logic
* Makes it easier to modify data storage implementation

### Implementation Details
* Implemented in repository.py
* Handles core data operations
* Abstracts storage details from command implementations

## Comprehensive Documentation Structure

### Decision
Organize documentation in hierarchical structure with separate concerns

### Rationale
* Improves maintainability of documentation
* Separates different types of documentation (technical, user guide, etc.)
* Makes it easier to find specific information

### Implementation Details
* Main sections: overview, technical, implementation, issues
* Each section has its own README and specific document files
* Separate guides for different user needs (setup, configuration, examples)