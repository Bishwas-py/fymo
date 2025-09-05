# FyMo Svelte 5 SSR Integration Plan

## Project Overview

**FyMo** is a full-stack monolith Python web framework that aims to render Svelte components on both client and server side. This plan outlines the roadmap to transform FyMo from a basic string-templating system into a modern framework with proper Svelte 5 server-side rendering (SSR) capabilities.

### Current State Analysis

#### FyMo (Current Implementation)
- **Architecture**: Basic WSGI-compatible Python web framework
- **Templating**: Simple string formatting (`{variable}` replacement)
- **Routing**: YAML-based configuration (`routes.yml`)
- **Controllers**: Python modules that export context dictionaries
- **Templates**: `.svelte` files treated as text templates
- **Limitations**: No actual Svelte compilation or JavaScript execution

#### Bud Framework (Reference Implementation)
Bud demonstrates sophisticated Svelte SSR implementation in Go:
- **V8 Integration**: Embedded JavaScript runtime using `rogchap.com/v8go`
- **Dual Compilation**: Each `.svelte` file compiled for both SSR and DOM targets
- **Code Generation**: Template-driven JavaScript entry point generation
- **ESBuild Integration**: Fast bundling with custom plugins
- **Hot Reloading**: Real-time updates via Server-Sent Events
- **Hydration Strategy**: Isomorphic rendering with client-side hydration

#### Svelte 5 Changes (Key Updates)
- **Component Architecture**: `SvelteComponent` → `Component` interface
- **Runes System**: New reactivity with `$state`, `$derived`, `$effect`, `$props`
- **Instantiation**: `new Component()` → `mount()`/`hydrate()` functions
- **Event Handling**: `createEventDispatcher` → callback props
- **SSR Functions**: Enhanced `hydrate()` function for server-rendered content

## Phase 1: Core SSR Implementation (Priority)

### 1.1 Svelte 5 Compiler Integration

**Goal**: Replace string formatting with actual Svelte compilation

**Implementation**:
```python
# fymo/svelte_compiler.py
class SvelteCompiler:
    def compile_ssr(self, svelte_source, filename):
        """Compile Svelte component for server-side rendering"""
        
    def compile_dom(self, svelte_source, filename):
        """Compile Svelte component for client-side hydration"""
```

**Technical Approach**:
- Use Node.js subprocess to run Svelte compiler
- Generate both SSR and DOM versions of components
- Cache compiled results for performance
- Handle compilation errors gracefully

**Dependencies**:
- `svelte@^5.0.0` (Node.js package)
- `@svelte/compiler@^5.0.0`

### 1.2 JavaScript Runtime Integration

**Goal**: Execute compiled Svelte components server-side

**Implementation**:
```python
# fymo/js_runtime.py
class JSRuntime:
    def render_component(self, compiled_js, props):
        """Execute Svelte SSR component and return HTML"""
```

**Technical Approach**:
- Integrate `STPyV8` for robust V8 JavaScript execution
- Use JSContext for isolated JavaScript execution environments
- Load Svelte runtime environment with proper error handling
- Execute compiled components with props using JSIsolate
- Return rendered HTML strings with comprehensive error reporting

**Dependencies**:
- `stpyv8` (Cloudflare's robust Python V8 bindings, successor to PyV8)

### 1.3 Updated Server Architecture

**Goal**: Modify existing server to support Svelte SSR

**Implementation**:
```python
# fymo/server.py (enhanced)
def render_svelte_template(path, context):
    """Render Svelte component with full SSR pipeline"""
    
def render_template(path):
    """Updated to detect and handle .svelte files"""
```

**Features**:
- Detect `.svelte` files vs regular templates
- Compile Svelte components on-demand
- Inject controller context as props
- Generate HTML with embedded state for hydration
- Fallback to existing string templating for non-Svelte files

### 1.4 Component State Management

**Goal**: Bridge Python controller context with Svelte props

**Implementation**:
- Convert Python dictionaries to JavaScript objects
- Serialize state for client-side hydration
- Handle data type conversions (dates, None values, etc.)
- Validate prop types against component expectations

## Phase 2: Client-Side Hydration (Future)

### 2.1 Hydration Infrastructure
- Generate client-side JavaScript bundles
- Implement hydration scripts
- State serialization/deserialization
- Progressive enhancement support

### 2.2 Asset Pipeline
- CSS extraction and optimization
- JavaScript bundling
- Static asset serving
- Cache management

## Phase 3: Development Experience (Future)

### 3.1 Hot Reloading
- File watching system
- Component-level updates
- State preservation during reloads
- Error overlay system

### 3.2 Development Tools
- Better error messages
- Component inspector
- Performance profiling
- Debug mode enhancements

## Phase 4: Advanced Features (Future)

### 4.1 Layout System
- Nested layouts support
- Layout composition
- Slot-based architecture
- Frame/wrapper components

### 4.2 Routing Enhancement
- File-system based routing
- Dynamic routes
- Route parameters
- Middleware support

### 4.3 State Management
- Server-side state persistence
- Client-server state sync
- Session management
- Real-time updates

## Technical Architecture

### Current FyMo Flow
```
Request → routes.yml → Controller (Python) → Template (String Format) → Response
```

### Proposed SSR Flow
```
Request → routes.yml → Controller (Python) → Svelte Compiler → JS Runtime → SSR HTML → Response
                                                                              ↓
                                                                    Client Hydration Script
```

### Component Compilation Pipeline
```
Component.svelte → Svelte Compiler → { ssr.js, dom.js, css } → Cache → Runtime Execution
```

## Implementation Details

### File Structure Changes
```
fymo/
├── svelte_compiler.py      # NEW: Svelte compilation logic
├── js_runtime.py          # NEW: JavaScript execution environment
├── server.py              # MODIFIED: Enhanced template rendering
├── controllers/           # EXISTING: Python context providers
├── templates/             # EXISTING: Now supports real .svelte files
├── static/               # NEW: Generated client assets
├── node_modules/         # NEW: Node.js dependencies
├── package.json          # NEW: Svelte dependencies
└── requirements.txt      # MODIFIED: Add py-mini-racer
```

### Example Svelte 5 Component
```svelte
<!-- templates/posts/index.svelte -->
<script>
  // Svelte 5 runes syntax
  let { id, content } = $props();
  
  let count = $state(0);
  let doubled = $derived(count * 2);
  
  function increment() {
    count++;
  }
</script>

<div class="post">
  <h1>Post #{id}</h1>
  <p>{content}</p>
  
  <div class="counter">
    <p>Count: {count} (doubled: {doubled})</p>
    <button onclick={increment}>Increment</button>
  </div>
</div>

<style>
  .post {
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 8px;
  }
</style>
```

### Controller Integration
```python
# controllers/posts/index.py
def getContext() -> dict:
    return {
        "id": 1,
        "content": "This framework now supports real Svelte SSR!"
    }

context = getContext()
```

## Dependencies & Requirements

### Python Dependencies
```txt
# requirements.txt
gunicorn==20.1.0
PyYAML==6.0
stpyv8    # Cloudflare's robust JavaScript V8 runtime
```

### Node.js Dependencies
```json
{
  "name": "fymo",
  "version": "1.0.0",
  "dependencies": {
    "svelte": "^5.0.0"
  },
  "devDependencies": {
    "@svelte/compiler": "^5.0.0"
  }
}
```

### System Requirements
- Python 3.9+ (STPyV8 officially supports Python 3.9+)
- Node.js 18+ (for Svelte compiler)
- V8 JavaScript engine (via STPyV8 - includes precompiled V8 binaries)
- Boost libraries (automatically handled by STPyV8 v12.0.267.16+)

## Success Metrics

### Phase 1 Success Criteria
- [ ] Svelte 5 components compile successfully
- [ ] Server-side rendering produces valid HTML
- [ ] Controller context properly injected as props
- [ ] Basic interactivity works (buttons, forms)
- [ ] Error handling for compilation failures
- [ ] Performance acceptable for development

### Quality Assurance
- Unit tests for compiler integration
- Integration tests for full SSR pipeline
- Performance benchmarks vs current implementation
- Memory usage monitoring
- Error handling validation

## Risk Assessment

### Technical Risks
- **JavaScript Runtime Overhead**: V8 integration may impact performance
- **Compilation Complexity**: Svelte compiler errors need proper handling
- **State Serialization**: Complex Python objects may not serialize cleanly
- **Memory Management**: JavaScript runtime memory leaks

### Mitigation Strategies
- Implement compilation caching
- Add comprehensive error handling using STPyV8's robust error reporting
- Create fallback to string templating
- Use STPyV8's context managers for proper resource cleanup
- Leverage STPyV8's JSIsolate for memory isolation
- Monitor memory usage and implement cleanup
- Gradual rollout with feature flags

## Learning from Bud Framework

### Key Insights Applied
1. **Dual Compilation Strategy**: Separate SSR and DOM compilation targets
2. **Template-Driven Generation**: Use templates to generate JavaScript entry points
3. **Plugin Architecture**: Extensible build system for different frameworks
4. **Caching Strategy**: Intelligent caching prevents unnecessary recompilation
5. **Development Experience**: Hot reloading and error handling are crucial

### Bud Techniques Adapted for Python
- **V8 Integration**: Use STPyV8 (Cloudflare's production-ready V8 bindings) instead of rogchap.com/v8go
- **JSContext Management**: Proper context isolation and cleanup using STPyV8's context managers
- **Error Handling**: Leverage STPyV8's comprehensive JavaScript error reporting
- **ESBuild Plugins**: Replace with Python-based asset pipeline
- **Go Templates**: Use Jinja2 or string templates for code generation
- **Filesystem Watching**: Use Python watchdog library
- **HTTP Server**: Leverage existing WSGI infrastructure

## Future Vision

### Long-term Goals
- **Multi-Framework Support**: React, Vue.js integration
- **TypeScript Support**: Full TypeScript compilation pipeline
- **Build Optimization**: Production bundling and minification
- **Plugin Ecosystem**: Extensible architecture for community plugins
- **Cloud Deployment**: Optimized for serverless and container deployment

### Inspiration Sources
- **Bud Framework**: Advanced SSR techniques and development experience
- **Next.js**: File-system routing and API design
- **SvelteKit**: Svelte-specific optimizations and conventions
- **Laravel**: Developer productivity and convention over configuration

## Getting Started

### Phase 1 Implementation Order
1. Set up Node.js environment and Svelte dependencies
2. Implement basic Svelte compiler wrapper
3. Integrate py-mini-racer JavaScript runtime
4. Modify server.py to detect and handle .svelte files
5. Create example Svelte 5 component with runes
6. Test full SSR pipeline with existing controller
7. Add error handling and fallback mechanisms
8. Performance testing and optimization

### Development Environment Setup
```bash
# Install Node.js dependencies
npm install

# Install Python dependencies
pip install -r requirements.txt

# Test Svelte compilation
python -c "from fymo.svelte_compiler import SvelteCompiler; print('Setup complete')"
```

This plan provides a comprehensive roadmap for transforming FyMo into a modern full-stack framework with proper Svelte 5 SSR support, drawing from the sophisticated techniques demonstrated in the Bud framework while adapting them for the Python ecosystem.
