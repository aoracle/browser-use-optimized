# Browser-Use DOM Processing Workflows

This document provides a complete guide to all DOM processing workflows in browser-use, using hierarchical numbering to show different paths through the system.

## Workflow Overview

The DOM processing system has multiple distinct workflows that handle different scenarios:

### Primary Workflows

1. **WORKFLOW 1.x**: Full DOM Extraction (Cache Miss)
2. **WORKFLOW 2.x**: Cached DOM Retrieval (Cache Hit)
3. **WORKFLOW 3.x**: Agent Action Execution
4. **WORKFLOW 4.x**: Error Recovery Flow
5. **WORKFLOW 5.x**: Empty/System Page Optimization

## Detailed Workflow Paths

### WORKFLOW 1.x: Full DOM Extraction (Cache Miss)

This is the complete path when DOM needs to be extracted from scratch.

```
1.0: JavaScript execution triggered by Python
1.1: Initialize DOM caching system
1.2: Set up highlight container for visual feedback
1.3: Extract and process DOM tree recursively
    1.3.1: Check if node should be processed
        1.3.1.1: Check parent element visibility
        1.3.1.2: Verify text content is non-empty
        1.3.1.3: Check if parent is in viewport
    1.3.2: Determine if node is interactive
    1.3.3: Create highlight if interactive and visible
    1.3.4: Store node data in hash map
    1.3.5: Process all child nodes recursively
    1.3.6: Handle special cases (iframes, shadow DOM)
1.4: Identify interactive elements
    1.4.1: Cursor style check (PRIMARY)
    1.4.2: Semantic HTML tags
    1.4.3: ARIA roles
    1.4.4: ContentEditable attribute
    1.4.5: Tabindex presence
1.5: Create visual highlights for clickable elements
    1.5.1: Create highlight overlay div
    1.5.2: Position it over the target element
    1.5.3: Add numbered label for identification
    1.5.4: Handle updates on scroll/resize
1.6: Return structured data to Python
    1.6.1: Start recursive DOM processing
    1.6.2: Clear cache to free memory
    1.6.3: Return structured data
1.7: Python receives request for DOM state
1.8: Check cache (miss - not found or expired)
1.9: Execute JavaScript DOM extraction
    1.9.1: Verify JavaScript execution capability
    1.9.2: Check for empty/system pages
    1.9.3: Prepare arguments for JavaScript
    1.9.4: Execute index.js in browser context
    1.9.5: Process returned data
1.10: Convert JavaScript results to Python objects
    1.10.1: Extract data from JavaScript response
    1.10.2: Parse each node into Python objects
    1.10.3: Build parent-child relationships
    1.10.4: Create selector map for quick lookups
    1.10.5: Return complete DOM tree
1.11: Cache and return DOM state
    1.11.1: Generate cache key
    1.11.2: Check cache capacity
    1.11.3: Evict oldest entry if needed (LRU)
    1.11.4: Store state with timestamp
    1.11.5: Track cache key for page cleanup
```

### WORKFLOW 2.x: Cached DOM Retrieval (Cache Hit)

This optimized path when DOM is already cached.

```
2.0: Python receives request for DOM state
2.1: Check cache for valid entry
    2.1.1: Generate cache key from URL and parameters
    2.1.2: Check if key exists in cache
    2.1.3: Validate entry hasn't expired (TTL check)
    2.1.4: Update LRU ordering if valid
    2.1.5: Return cached state or None
2.2: Return cached DOM state immediately (skip extraction)
```

### WORKFLOW 3.x: Agent Action Execution

This workflow handles agent interactions with DOM elements.

```
3.0: Agent prepares context for decision
    3.0.1: Request browser state (triggers DOM workflows)
    3.0.2: Get current page reference
    3.0.3: Update available actions for the page
    3.0.4: Prepare DOM state for LLM
3.1: Execute click action on DOM element
    3.1.1: Look up element by highlight index
        3.1.1.1: Get the current selector map
        3.1.1.2: Look up element by highlight index
        3.1.1.3: Return DOMElementNode or None
    3.1.2: Validate element exists and is clickable
    3.1.3: Execute click via browser automation
        3.1.3.1: Get Playwright element handle from XPath
        3.1.3.2: Set up download monitoring
        3.1.3.3: Execute click action
        3.1.3.4: Handle side effects (downloads, navigation)
    3.1.4: Handle side effects (downloads, new tabs)
```

### WORKFLOW 4.x: Error Recovery Flow

This workflow handles errors during DOM extraction.

```
4.0: JavaScript execution fails
4.1: Python catches error
4.2: Fallback to minimal DOM state
4.3: Log error for debugging
4.4: Return minimal state to allow basic navigation
```

### WORKFLOW 5.x: Empty/System Page Optimization

This workflow optimizes handling of empty tabs and system pages.

```
5.0: Detect empty tab or chrome:// page
5.1: Skip JavaScript execution entirely
5.2: Return minimal DOM structure
5.3: Avoid unnecessary processing overhead
```

## Workflow Decision Tree

```
Agent requests browser state
    │
    ├─► Is page empty/system? ──YES──► WORKFLOW 5.x
    │                                   (Skip extraction)
    │   NO
    ▼
    Check DOM cache
    │
    ├─► Cache hit? ──YES──► WORKFLOW 2.x
    │                      (Return cached)
    │   NO
    ▼
    WORKFLOW 1.x
    (Full extraction)
    │
    ├─► JavaScript error? ──YES──► WORKFLOW 4.x
    │                              (Error recovery)
    │   NO
    ▼
    Success - DOM extracted
    │
    ▼
    Agent makes decision
    │
    ▼
    WORKFLOW 3.x
    (Execute action)
```

## Performance Characteristics by Workflow

| Workflow | Typical Time | Cache Status | Use Case |
|----------|--------------|--------------|----------|
| 1.x | 200ms | Miss | First visit to page |
| 2.x | 3ms | Hit | Repeated queries within 2s |
| 3.x | 50ms | N/A | Action execution |
| 4.x | 100ms | N/A | Error recovery |
| 5.x | 5ms | N/A | Empty page optimization |

## Workflow Interactions

### Cache Warming
- First agent step always follows Workflow 1.x
- Subsequent steps within 2s follow Workflow 2.x
- Cache invalidated on navigation

### Error Cascading
- Workflow 4.x can trigger from any point in 1.x
- Minimal DOM allows Workflow 3.x to continue
- Agent can retry with full Workflow 1.x

### Optimization Triggers
- Workflow 5.x checked before all others
- Saves ~195ms on empty pages
- Common during multi-tab operations

## Implementation Details

### Cache Key Generation
```python
key = hashlib.md5(f"{page.url}|{highlight}|{focus}|{viewport}".encode()).hexdigest()
```

### TTL Management
- Default: 2 seconds
- Configurable via environment variable
- Per-page tracking with WeakKeyDictionary

### LRU Eviction
- Default capacity: 100 entries
- Oldest entry removed when full
- Access order tracked in list

### JavaScript Optimizations
- WeakMap caching for DOM APIs
- Throttled update functions (16ms)
- Early exit for non-visible elements

## Best Practices

1. **Workflow Selection**
   - Let the system route automatically
   - Don't force cache invalidation
   - Trust TTL settings

2. **Error Handling**
   - Always implement Workflow 4.x fallbacks
   - Log errors for debugging
   - Allow agent to continue with minimal DOM

3. **Performance Tuning**
   - Increase cache TTL for stable pages
   - Reduce viewport expansion for faster extraction
   - Use Workflow 5.x detection aggressively

4. **Debugging**
   - Check workflow paths in logs
   - Monitor cache hit rates
   - Track extraction times by workflow