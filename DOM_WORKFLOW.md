# Browser-Use DOM Processing Workflow

This document provides a complete step-by-step walkthrough of how DOM extraction and processing works in browser-use.

## Overview

The DOM processing system extracts interactive elements from web pages and makes them accessible to AI agents. The workflow involves JavaScript execution in the browser, Python orchestration, caching, and element identification.

## Complete Workflow Steps

### 🚀 INITIALIZATION PHASE

#### STEP 0: Agent Initialization
- **Location**: `browser_use/agent/service.py`
- Agent is created with a task and LLM
- Browser session is initialized
- DOM service is attached to the browser page

### 🔍 DOM EXTRACTION PHASE

#### STEP 1: Agent Requests Page State
- **Location**: `browser_use/agent/service.py` → `_get_browser_state()`
- Agent needs to understand current page
- Calls `browser_session.get_state_summary()`

#### STEP 2: Browser Session Prepares State
- **Location**: `browser_use/browser/session.py` → `get_state_summary()`
- Takes screenshot of page
- Calls DOM service to get clickable elements

#### STEP 3: DOM Service Entry Point
- **Location**: `browser_use/dom/service.py` → `get_clickable_elements()`
- **Parameters**:
  - `highlight_elements`: Create visual overlays (default: True)
  - `focus_element`: Specific element to focus (-1 for none)
  - `viewport_expansion`: Pixels to expand viewport (0 default)

#### STEP 4: Cache Check
- **Location**: `browser_use/dom/cache.py` → `get()`
- **Process**:
  1. Generate cache key from URL + parameters
  2. Check if entry exists and hasn't expired (2s TTL)
  3. Return cached state if valid
  4. Continue to extraction if cache miss

### 🌐 JAVASCRIPT EXECUTION PHASE

#### STEP 5: JavaScript Preparation
- **Location**: `browser_use/dom/service.py` → `_build_dom_tree()`
- **Checks**:
  - Verify JavaScript can execute (`1+1 == 2`)
  - Skip empty tabs and chrome:// pages
  - Prepare arguments for JavaScript

#### STEP 6: JavaScript DOM Extraction
- **Location**: `browser_use/dom/dom_tree/index.js`
- **Main Function Flow**:

##### 6.1: Initialize Caching
```javascript
const DOM_CACHE = {
    boundingRects: new WeakMap(),
    clientRects: new WeakMap(),
    computedStyles: new WeakMap()
};
```

##### 6.2: Visibility Detection
- `isTextNodeVisible()`: Check if text is visible
- `isInExpandedViewport()`: Check if element is in viewport
- `isTopElement()`: Verify element is clickable (not covered)

##### 6.3: Interactivity Detection
```javascript
function isInteractiveElement(element) {
    // PRIMARY: Check cursor style (fastest, most reliable)
    if (interactiveCursors.has(style.cursor)) return true;
    
    // SECONDARY: Check semantic HTML tags
    if (interactiveTags.has(tagName)) return true;
    
    // TERTIARY: Check ARIA roles, contenteditable, etc.
}
```

##### 6.4: DOM Tree Building
```javascript
function buildDomTree(node, parentIframe, isParentHighlighted) {
    // 1. Check visibility
    // 2. Determine if interactive
    // 3. Create highlight if needed
    // 4. Process children recursively
    // 5. Store in hash map
}
```

##### 6.5: Return Results
```javascript
return { 
    rootId: "0",  // ID of body element
    map: {        // Hash map of all nodes
        "0": { tagName: "body", children: [...] },
        "1": { tagName: "a", highlightIndex: 0, ... },
        // ... more nodes
    }
};
```

### 🐍 PYTHON PROCESSING PHASE

#### STEP 7: JavaScript Result Processing
- **Location**: `browser_use/dom/service.py` → `_construct_dom_tree()`
- **Process**:
  1. Extract `rootId` and `map` from JavaScript
  2. Create Python `DOMElementNode` objects
  3. Build parent-child relationships
  4. Create `selector_map` (index → element)

#### STEP 8: Cache Storage
- **Location**: `browser_use/dom/cache.py` → `set()`
- **Process**:
  1. Generate cache key
  2. Check cache capacity (LRU eviction if full)
  3. Store with timestamp
  4. Track by page for cleanup

#### STEP 9: Return to Agent
- **Location**: Back through the call stack
- **Returns**: `DOMState` containing:
  - `element_tree`: Root node with all children
  - `selector_map`: Quick lookup by highlight index

### 🤖 AGENT ACTION PHASE

#### STEP 10: Agent Processes DOM
- **Location**: `browser_use/agent/service.py`
- **Process**:
  1. Agent receives DOM state with screenshot
  2. LLM analyzes and decides action
  3. Returns action like `click(5)` or `type("hello")`

#### STEP 11: Action Execution
- **Location**: `browser_use/controller/service.py`
- **Process**:
  1. Parse action parameters
  2. Look up element in selector_map
  3. Execute browser action (click, type, etc.)

#### STEP 12: State Update
- **Location**: Back to STEP 1
- Agent requests new page state after action
- Process repeats with updated DOM

## Key Optimizations

### 1. DOM Caching
- **TTL**: 2 seconds default
- **LRU**: Evict oldest when full
- **Page-aware**: Auto-cleanup on navigation

### 2. JavaScript Caching
- **WeakMaps**: For DOM API results
- **XPath cache**: Reuse computed paths
- **Style cache**: Avoid recomputing styles

### 3. Smart Detection
- **Cursor style first**: Fastest interactive check
- **Viewport culling**: Only process visible elements
- **Batch operations**: Process all nodes in one pass

### 4. Memory Management
- **Weak references**: Auto garbage collection
- **Limited cache size**: Prevent memory bloat
- **Selective processing**: Skip hidden elements

## Data Flow Diagram

```
┌─────────────┐
│    Agent    │
│ ┌─────────┐ │
│ │   LLM   │ │
│ └────┬────┘ │
│      │      │
│  Decides    │
│  Action     │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────┐
│   Browser   │────▶│  DOM Cache   │
│   Session   │     │              │
└──────┬──────┘     │  TTL: 2sec   │
       │            │  LRU: 100    │
       │            └──────────────┘
       ▼
┌─────────────┐
│ DOM Service │
│             │
│ Orchestrates│
│ Extraction  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ JavaScript  │
│ Execution   │
│             │
│ - Visibility│
│ - Interactive│
│ - Highlights│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Python    │
│ Processing  │
│             │
│ Builds Tree │
└─────────────┘
```

## Performance Characteristics

| Operation | Time | Cached Time |
|-----------|------|-------------|
| Full DOM Extraction | 200ms | 3ms |
| JavaScript Execution | 150ms | - |
| Python Processing | 50ms | - |
| Cache Lookup | - | 1ms |
| Screenshot | 100ms | 100ms |

## Common Issues & Solutions

### 1. Dynamic Content
- **Problem**: Elements change after extraction
- **Solution**: Element hashing detects changes

### 2. Performance on Large Pages
- **Problem**: Thousands of elements slow extraction
- **Solution**: Viewport culling + cursor style detection

### 3. Memory Usage
- **Problem**: Large DOM trees consume memory
- **Solution**: WeakMap caching + TTL expiration

### 4. Cross-origin iframes
- **Problem**: Cannot access iframe content
- **Solution**: Detect and report separately

## Best Practices

1. **Use viewport expansion** carefully - larger values mean more processing
2. **Enable highlights** only when debugging - slight performance cost
3. **Trust the cache** - 2 second TTL is usually sufficient
4. **Monitor memory** - Use memory manager for long-running agents
5. **Handle failures** gracefully - DOM extraction can fail on some pages