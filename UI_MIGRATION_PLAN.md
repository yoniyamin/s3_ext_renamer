# S3 Manipulator UI Migration Plan

## Overview
This document outlines the complete migration from a step-based wizard interface to an integrated file browser-centric UI with enhanced UX.

## Current Structure Analysis

### Current Wizard Flow:
1. **Step 1**: Action Selection (presigned, parser, rename, filebrowser)
2. **Step 2**: Credentials (AWS credentials + region)
3. **Step 3**: Configuration (action-specific settings)
4. **Step 4**: Results (execution results)

### Current Key Files:
- `s3bucket_wizard.py` - Flask backend with all routes
- `templates/wizard.html` - Main wizard interface (4595 lines)
- `templates/upload_form.html` - Upload form
- Various other templates

### Current Features:
- Secure session management
- Presigned URL generation/parsing
- Extension renaming operations
- File browser with context menus
- S3 bucket listing and file management

## Target Architecture

### New Flow:
1. **Landing Screen**: Credentials + Bucket Selection + Parse Presigned URL link
2. **Main Interface**: Enhanced File Browser (replaces wizard steps)
3. **Action Modals**: Separate templates for each operation
4. **Connection Management**: Easy bucket switching and credential management

---

## Migration Steps

### Phase 1: Prepare New Template Structure
**Estimated Time**: 2-3 hours

#### Step 1.1: Create New Landing Template
**Prompt**: *Create a new `templates/landing.html` template that combines credential entry with bucket selection and a quick access link for parsing presigned URLs*

**Details**:
- Copy credential section from current Step 2
- Add Select2 bucket selection field (from current filebrowser config)
- Add prominent "Parse Presigned URL" button that doesn't require credentials
- Style similar to current wizard but simpler layout
- Include connection status feedback

**Files to create**:
- `templates/landing.html`

**Key requirements**:
- Responsive design
- Form validation
- Session management integration
- Bucket dropdown population

#### Step 1.2: Create Action Modal Templates
**Prompt**: *Extract and create separate modal templates for each action type*

**Templates to create**:
- `templates/modals/upload_link_modal.html` - Upload presigned URL generation
- `templates/modals/download_link_modal.html` - Download presigned URL generation  
- `templates/modals/rename_extension_modal.html` - Extension renaming operations
- `templates/modals/verify_upload_modal.html` - Upload verification
- `templates/modals/parse_url_modal.html` - URL parsing (enhanced from current)

**Key requirements**:
- Each modal should have config and results sections
- Consistent styling with current wizard
- Self-contained JavaScript per modal
- Form validation and error handling

#### Step 1.3: Create Enhanced File Browser Template
**Prompt**: *Create a new `templates/file_browser.html` template that will serve as the main application interface*

**Details**:
- Extract file browser functionality from current wizard
- Add "Connected to <bucket>" header button
- Integrate radial menu component
- Add action toolbar for selected items
- Enhanced selection UI with bulk operations

**Key requirements**:
- Full-screen layout (not modal)
- File/folder navigation
- Multiple selection support
- Context-sensitive action availability
- Search functionality

---

### Phase 2: Implement Radial Menu Component
**Estimated Time**: 2-3 hours

#### Step 2.1: Create Radial Menu CSS and JavaScript
**Prompt**: *Implement a radial menu component for file browser actions*

**Files to create**:
- `static/css/radial-menu.css`
- `static/js/radial-menu.js`

**Features**:
- Circular menu that appears on action button click
- Icons for each action type
- Smooth animations
- Context-aware menu items (based on selection type)
- Mobile-friendly touch support

**Actions to include**:
- Rename Extension (files only)
- Verify Upload (files only)
- Generate Upload Link (folders only)
- Generate Download Link (files and folders)
- Parse Presigned URL (always available)

#### Step 2.2: Integrate Radial Menu in File Browser
**Prompt**: *Add radial menu trigger button to file browser selection toolbar*

**Details**:
- Add "Actions" button in selection info area
- Position radial menu relative to button
- Handle menu item clicks to open appropriate modals
- Update menu items based on current selection

---

### Phase 3: Backend Route Updates
**Estimated Time**: 2-3 hours

#### Step 3.1: Create New Landing Route
**Prompt**: *Add new route for landing page and update main index route*

**Changes needed**:
- Modify `@app.route("/")` to serve landing template
- Create `@app.route("/browser")` for file browser interface
- Update session handling for new flow

#### Step 3.2: Update Authentication Flow
**Prompt**: *Modify authentication to support direct bucket connection*

**Changes needed**:
- Update `/auth/login` to handle bucket selection
- Add `/auth/change-bucket` endpoint for bucket switching
- Modify session storage to include selected bucket
- Add bucket validation in authentication

#### Step 3.3: Create Modal Action Endpoints
**Prompt**: *Create dedicated endpoints for each modal action*

**New endpoints**:
- `/actions/generate-upload-link` 
- `/actions/generate-download-link`
- `/actions/rename-extension`
- `/actions/verify-upload`
- `/actions/parse-url` (enhanced)

**Requirements**:
- Consistent JSON response format
- Session-based authentication
- Progress tracking for long operations
- Error handling and validation

---

### Phase 4: Frontend Integration
**Estimated Time**: 3-4 hours

#### Step 4.1: Update Main JavaScript Architecture
**Prompt**: *Refactor main JavaScript to support new modal-based architecture*

**Files to modify**:
- Extract wizard navigation logic
- Create modal management system
- Update session handling
- Add connection state management

**Key changes**:
- Remove step-based navigation
- Add modal lifecycle management
- Implement connection status monitoring
- Update error handling

#### Step 4.2: Implement Connection Management
**Prompt**: *Add "Connected to <bucket>" button functionality*

**Features**:
- Display current connection status
- Click to show connection options
- Quick bucket switching without re-authentication
- Credential update option
- Session timeout handling

#### Step 4.3: Enhanced File Browser Features
**Prompt**: *Add enhanced selection and action features to file browser*

**Enhancements**:
- Multiple file selection with Ctrl/Shift support
- Bulk action toolbar
- Selection summary (count, total size)
- Context-sensitive action availability
- Keyboard shortcuts

---

### Phase 5: Modal Implementation and Testing
**Estimated Time**: 4-5 hours

#### Step 5.1: Implement Upload Link Modal
**Prompt**: *Create upload link generation modal with form and results*

**Features**:
- Folder selection (read-only, based on browser selection)
- Expiration time configuration
- Upload limit settings
- QR code generation option
- Copy to clipboard functionality

#### Step 5.2: Implement Download Link Modal
**Prompt**: *Create download link generation modal*

**Features**:
- File/folder selection display
- Expiration configuration
- Bulk download options for folders
- Link preview and validation
- Share options (email, copy, QR code)

#### Step 5.3: Implement Rename Extension Modal
**Prompt**: *Create extension renaming modal*

**Features**:
- Selected files preview
- Source/target extension specification
- Backup options
- Progress tracking
- Rollback capability

#### Step 5.4: Implement Verify Upload Modal
**Prompt**: *Create upload verification modal*

**Features**:
- File integrity checking
- Checksum verification
- Metadata validation
- Progress reporting
- Detailed results display

---

### Phase 6: Styling and Polish
**Estimated Time**: 2-3 hours

#### Step 6.1: Update CSS Architecture
**Prompt**: *Reorganize CSS for new component-based structure*

**Changes**:
- Extract reusable modal styles
- Create component-specific stylesheets
- Update responsive design for new layout
- Ensure consistent theming

#### Step 6.2: Mobile Optimization
**Prompt**: *Optimize interface for mobile devices*

**Features**:
- Touch-friendly radial menu
- Responsive file browser
- Modal adaptations for small screens
- Gesture support for navigation

---

### Phase 7: Testing and Migration
**Estimated Time**: 2-3 hours

#### Step 7.1: Create Migration Script
**Prompt**: *Create utility script to help with the transition*

**Features**:
- Backup current configuration
- Migrate existing sessions
- Update any stored preferences
- Data integrity validation

#### Step 7.2: Comprehensive Testing
**Prompt**: *Test all functionality across different scenarios*

**Test scenarios**:
- Authentication flow
- Bucket switching
- All modal operations
- File browser navigation
- Error handling
- Session management
- Mobile compatibility

---

## Implementation Guidelines

### Code Organization
- Keep each modal's JavaScript in separate files
- Use consistent naming conventions
- Implement proper error handling in all components
- Maintain backward compatibility during transition

### UI/UX Principles
- Maintain visual consistency with current design
- Ensure accessibility compliance
- Provide clear feedback for all actions
- Implement progressive disclosure for advanced features

### Performance Considerations
- Lazy load modal content
- Cache bucket listings appropriately
- Implement debounced search functionality
- Optimize file listing for large directories

### Security Requirements
- Maintain current session security model
- Validate all user inputs
- Secure credential handling
- Implement proper CSRF protection

---

## File Structure After Migration

```
templates/
├── landing.html              # New credential + bucket selection
├── file_browser.html         # Main file browser interface
├── modals/
│   ├── upload_link_modal.html
│   ├── download_link_modal.html
│   ├── rename_extension_modal.html
│   ├── verify_upload_modal.html
│   └── parse_url_modal.html
└── components/              # Reusable components
    ├── radial_menu.html
    └── connection_status.html

static/
├── css/
│   ├── main.css            # Base styles
│   ├── file-browser.css    # File browser specific
│   ├── modals.css          # Modal system styles
│   └── radial-menu.css     # Radial menu component
└── js/
    ├── main.js             # Core application logic
    ├── file-browser.js     # File browser functionality
    ├── modal-manager.js    # Modal system
    ├── radial-menu.js      # Radial menu component
    └── connection-manager.js # Connection handling
```

---

## Risk Mitigation

### Backward Compatibility
- Keep old wizard route available during transition
- Maintain existing API endpoints
- Provide migration path for existing users

### Rollback Plan
- Git branch for entire migration
- Database/session backup before migration
- Quick rollback procedure documented
- Feature flags for gradual rollout

### Testing Strategy
- Unit tests for new components
- Integration tests for user flows
- Cross-browser compatibility testing
- Mobile device testing
- Performance benchmarking

---

## Success Metrics

### User Experience
- Reduced clicks to complete common tasks
- Faster navigation between operations
- Improved mobile usability
- Better discoverability of features

### Technical Metrics
- Reduced page load times
- Cleaner code organization
- Better maintainability
- Improved error handling

### Functional Goals
- All current functionality preserved
- Enhanced file browser capabilities
- Streamlined connection management
- Improved action discoverability

---

## Next Steps

1. **Review and approve this plan**
2. **Set up development branch**
3. **Begin with Phase 1, Step 1.1**
4. **Implement in order, testing each phase**
5. **Deploy to staging for user testing**
6. **Production rollout with rollback capability**

Each step should be implemented as a separate commit with thorough testing before proceeding to the next step.
