// Help Modal Module
const HelpModal = {
    // Load the help modal HTML
    async loadModal() {
        try {
            // Try the static route first
            const response = await fetch('/static/help-modal.html');
            if (!response.ok) {
                throw new Error(`Failed to load help modal: ${response.status}`);
            }
            const modalHTML = await response.text();
            
            // Create a container div and append to body
            const modalContainer = document.createElement('div');
            modalContainer.innerHTML = modalHTML;
            document.body.appendChild(modalContainer);
            
            console.log('Help modal loaded successfully');
            return true;
        } catch (error) {
            console.error('Error loading help modal:', error);
            return false;
        }
    },

    // Initialize help modal functionality
    initialize() {
        this.loadModal().then(success => {
            if (success) {
                this.setupEventHandlers();
            } else {
                console.error('Failed to load help modal, creating fallback');
                this.createFallbackModal();
            }
        });
    },

    // Set up event handlers for the help modal
    setupEventHandlers() {
        // Help modal open/close handlers
        const helpBtn = document.getElementById('helpBtn');
        const closeHelp = document.getElementById('closeHelp');
        const closeHelpBtn = document.getElementById('closeHelpBtn');
        const helpModal = document.getElementById('helpModal');

        if (!helpBtn || !closeHelp || !closeHelpBtn || !helpModal) {
            console.error('Help modal elements not found, retrying in 500ms...');
            setTimeout(() => this.setupEventHandlers(), 500);
            return;
        }

        // Open modal
        helpBtn.addEventListener('click', () => {
            helpModal.style.display = 'block';
        });

        // Close modal handlers
        closeHelp.addEventListener('click', () => {
            helpModal.style.display = 'none';
        });

        closeHelpBtn.addEventListener('click', () => {
            helpModal.style.display = 'none';
        });

        // Close modal when clicking outside
        window.addEventListener('click', (event) => {
            if (event.target === helpModal) {
                helpModal.style.display = 'none';
            }
        });

        // Tab switching functionality
        this.setupTabSwitching();

        console.log('Help modal event handlers initialized');
    },

    // Set up tab switching functionality
    setupTabSwitching() {
        const helpTabs = document.querySelectorAll('.help-tab');
        
        if (helpTabs.length === 0) {
            console.error('Help tabs not found, retrying in 500ms...');
            setTimeout(() => this.setupTabSwitching(), 500);
            return;
        }

        helpTabs.forEach(tab => {
            tab.addEventListener('click', function() {
                const targetTab = this.getAttribute('data-tab');
                
                // Remove active class from all tabs and content
                document.querySelectorAll('.help-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.help-tab-content').forEach(content => content.classList.remove('active'));
                
                // Add active class to clicked tab and corresponding content
                this.classList.add('active');
                const targetContent = document.getElementById(targetTab);
                if (targetContent) {
                    targetContent.classList.add('active');
                }
            });
        });

        console.log('Help tab switching initialized');
    },

    // Fallback: Create modal inline if loading fails
    createFallbackModal() {
        const helpModal = document.createElement('div');
        helpModal.id = 'helpModal';
        helpModal.className = 'modal';
        helpModal.style.display = 'none';
        helpModal.innerHTML = `
            <div class="modal-content" style="width: 90%; max-width: 900px; height: 85vh;">
                <div class="modal-header">
                    <h3>📚 The Bucket Wizard - Help & Documentation</h3>
                    <span class="close" id="closeHelp">&times;</span>
                </div>
                <div class="modal-body" style="padding: 20px;">
                    <div class="help-section">
                        <h4>🚀 Getting Started</h4>
                        <p>Help content failed to load. Please refresh the page to try again.</p>
                        <p>If the problem persists, you can find documentation in the application's README file.</p>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" id="closeHelpBtn" class="btn" style="background: #6c757d;">Close</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(helpModal);
        this.setupEventHandlers();
        console.log('Fallback help modal created');
    }
};

// Initialize help modal when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    HelpModal.initialize();
});

// Export for potential external use
window.HelpModal = HelpModal;
