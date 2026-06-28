let sourceMessageEditor = null;
let isHtmlMode = false;
let isEditMode = false;

// Character counting functionality
function updateCharacterCount() {
    if (!sourceMessageEditor) return;
    
    const content = sourceMessageEditor.getValue();
    const charCount = document.getElementById('source-edit-char-count');
    if (charCount) {
        const length = content.length;
        const words = content.trim().split(/\s+/).filter(word => word.length > 0).length;
        charCount.textContent = `${length.toLocaleString()} characters, ${words.toLocaleString()} words`;
    }
}

// Add keyboard shortcuts
function addKeyboardShortcuts() {
    if (!sourceMessageEditor || !sourceMessageEditor.textarea) return;
    
    sourceMessageEditor.textarea.addEventListener('keydown', function(e) {
        // Ctrl+S to save
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            saveSourceEdit();
        }
        // Escape to cancel
        if (e.key === 'Escape') {
            e.preventDefault();
            cancelSourceEdit();
        }
    });
    
    // Update character count on input
    sourceMessageEditor.textarea.addEventListener('input', updateCharacterCount);
}

// Initialize the source message editor using the same pattern as events modal
function initSourceMessageEditor(containerId = 'source-edit-textarea-container') {
    if (!sourceMessageEditor) {
        const container = document.getElementById(containerId);
        if (!container) {
            console.warn(`Editor container ${containerId} not found`);
            return;
        }
        
        // Create a simple textarea-based editor for now
        const textarea = document.createElement('textarea');
        textarea.className = 'w-full h-full border-0 outline-0 resize-none bg-transparent text-sm font-mono p-3';
        textarea.style.minHeight = '200px';
        textarea.placeholder = 'Enter or edit your message content here...';
        container.innerHTML = '';
        container.appendChild(textarea);
        
        sourceMessageEditor = {
            container: container,
            textarea: textarea,
            getValue: () => textarea.value,
            setValue: (value) => { 
                textarea.value = value || ''; 
                updateCharacterCount();
            },
            focus: () => textarea.focus(),
            state: {
                doc: {
                    toString: () => textarea.value
                }
            },
            dispatch: (change) => {
                if (change.changes && change.changes.insert !== undefined) {
                    textarea.value = change.changes.insert;
                    updateCharacterCount();
                }
            }
        };
        
        // Add keyboard shortcuts and character counting
        addKeyboardShortcuts();
        updateCharacterCount();
    }
}

// Enhanced source message preview update function (reusing events modal logic)
async function updateSourceMessagePreview(content, container) {
    if (!container) return;

    // Show loading state
    container.innerHTML = `
        <div class="flex items-center justify-center py-4">
            <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
        </div>
    `;

    try {
        // Process content asynchronously
        const processedContent = await new Promise((resolve) => {
            setTimeout(() => {
                let html = '';
                
                // Format and sanitize the content
                if (content) {
                    // Use formatMessageContent if available, otherwise basic formatting
                    const formattedContent = typeof formatMessageContent === 'function' 
                        ? formatMessageContent(content, 'html') 
                        : content;
                    
                    if (formattedContent.length > 10000) {
                        html += `<div class="text-xs text-yellow-600 mb-2">
                            <i class="fas fa-exclamation-triangle mr-1"></i>
                            Large message (${formattedContent.length.toLocaleString()} characters)
                        </div>`;
                    }
                    html += `<div class="message-content">${formattedContent}</div>`;
                } else {
                    html += `<div class="text-gray-400 italic">No content available</div>`;
                }

                resolve(html);
            }, 50);
        });

        // Update the container with processed content
        container.innerHTML = processedContent;

        // Initialize any syntax highlighting if needed
        if (window.Prism) {
            container.querySelectorAll('pre code').forEach((block) => {
                Prism.highlightElement(block);
            });
        }
    } catch (error) {
        console.error('Error updating source message preview:', error);
        container.innerHTML = `
            <div class="text-red-500">
                <i class="fas fa-exclamation-circle mr-2"></i>
                Error displaying content
            </div>
        `;
    }
}

// Enhanced toggle edit mode function
function toggleSourceEditMode() {
    const editArea = document.getElementById('source-edit-area');
    const messageBlock = document.getElementById('source-message-block');
    const rawHtmlSource = document.getElementById('raw-html-source');
    const editBtn = document.getElementById('editSourceBtn');
    
    if (!editArea || !messageBlock || !editBtn) return;
    
    isEditMode = !isEditMode;
    
    if (isEditMode) {
        // Enter edit mode - hide all previews, show editor
        editArea.classList.remove('hidden');
        messageBlock.classList.add('hidden');
        if (rawHtmlSource) rawHtmlSource.classList.add('hidden');
        
        // Initialize editor if not already done
        initSourceMessageEditor('source-edit-textarea-container');
        
        // Get current content and set it in editor
        const currentContent = document.getElementById('source-message-content');
        if (currentContent && sourceMessageEditor) {
            sourceMessageEditor.setValue(currentContent.textContent.trim());
            sourceMessageEditor.focus();
        }
        
        // Update button text
        editBtn.innerHTML = '<i class="fas fa-times fa-sm"></i><span>Cancel</span>';
        editBtn.onclick = cancelSourceEdit;
        
    } else {
        // Exit edit mode - show preview, hide editor
        editArea.classList.add('hidden');
        messageBlock.classList.remove('hidden');
        if (rawHtmlSource) rawHtmlSource.classList.add('hidden');
        
        // Update button text
        editBtn.innerHTML = '<i class="fas fa-edit fa-sm"></i><span>Edit</span>';
        editBtn.onclick = toggleSourceEditMode;
    }
}

// Enhanced save function
async function saveSourceEdit() {
    if (!sourceMessageEditor) return;
    
    const saveBtn = document.querySelector('#source-edit-area button[onclick="saveSourceEdit()"]');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin fa-sm"></i> Saving...';
    }
    
    try {
        const content = sourceMessageEditor.getValue();
        const previewContainer = document.getElementById('source-message-content');
        
        if (previewContainer) {
            // Update the preview with new content
            await updateSourceMessagePreview(content, previewContainer);
            
            // Exit edit mode - hide editor, show preview
            const editArea = document.getElementById('source-edit-area');
            const messageBlock = document.getElementById('source-message-block');
            const rawHtmlSource = document.getElementById('raw-html-source');
            
            if (editArea) editArea.classList.add('hidden');
            if (messageBlock) messageBlock.classList.remove('hidden');
            if (rawHtmlSource) rawHtmlSource.classList.add('hidden');
            
            // Reset edit button
            const editBtn = document.getElementById('editSourceBtn');
            if (editBtn) {
                editBtn.innerHTML = '<i class="fas fa-edit fa-sm"></i><span>Edit</span>';
                editBtn.onclick = toggleSourceEditMode;
            }
            
            // Update edit mode state
            isEditMode = false;
            
            // Trigger translation update
            const messageForm = document.getElementById('message-form');
            if (messageForm) {
                // Update the hidden field if it exists
                const hiddenTextArea = messageForm.querySelector('textarea[name="selected_message_text"]');
                if (hiddenTextArea) {
                    hiddenTextArea.value = content;
                }
                
                // Trigger form submission
                const event = new Event('submit', { bubbles: true, cancelable: true });
                messageForm.dispatchEvent(event);
            }
            
            // Show success feedback
            showToast('Source message updated and translation triggered', 'success');
        }
    } catch (error) {
        console.error('Error saving source edit:', error);
        showToast('Failed to save changes. Please try again.', 'error');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fas fa-save fa-sm"></i> Save & Translate';
        }
    }
}

// Enhanced cancel function
function cancelSourceEdit() {
    // Hide editor and show preview
    const editArea = document.getElementById('source-edit-area');
    const messageBlock = document.getElementById('source-message-block');
    const rawHtmlSource = document.getElementById('raw-html-source');
    const editBtn = document.getElementById('editSourceBtn');
    
    if (editArea) editArea.classList.add('hidden');
    if (messageBlock) messageBlock.classList.remove('hidden');
    if (rawHtmlSource) rawHtmlSource.classList.add('hidden');
    
    // Reset edit button
    if (editBtn) {
        editBtn.innerHTML = '<i class="fas fa-edit fa-sm"></i><span>Edit</span>';
        editBtn.onclick = toggleSourceEditMode;
    }
    
    // Update edit mode state
    isEditMode = false;
}

// Enhanced HTML toggle function
function toggleHtmlMode() {
    isHtmlMode = !isHtmlMode;
    const toggleBtn = document.getElementById('toggle-html-btn') || document.getElementById('toggleRawBtn');
    const sourceBlock = document.getElementById('source-message-block');
    const rawHtmlSource = document.getElementById('raw-html-source');
    const editArea = document.getElementById('source-edit-area');
    
    // Only toggle if we're not in edit mode
    if (isEditMode && editArea && !editArea.classList.contains('hidden')) {
        // If in edit mode, don't toggle HTML view
        return;
    }
    
    if (toggleBtn) {
        const icon = toggleBtn.querySelector('i');
        const span = toggleBtn.querySelector('span');
        
        if (isHtmlMode) {
            if (icon) icon.className = 'fas fa-file-alt';
            if (span) span.textContent = 'Show Preview';
            if (sourceBlock) sourceBlock.style.display = 'none';
            if (rawHtmlSource) rawHtmlSource.style.display = 'block';
        } else {
            if (icon) icon.className = 'fas fa-code';
            if (span) span.textContent = 'Toggle Raw HTML';
            if (sourceBlock) sourceBlock.style.display = 'block';
            if (rawHtmlSource) rawHtmlSource.style.display = 'none';
        }
    }
}

// Toast notification function (reused from events modal)
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg transition-all duration-300 transform translate-y-full z-50 ${
        type === 'error' ? 'bg-red-500 text-white' :
        type === 'success' ? 'bg-green-500 text-white' :
        'bg-blue-500 text-white'
    }`;
    
    toast.textContent = message;
    document.body.appendChild(toast);
    
    // Animate in
    setTimeout(() => {
        toast.style.transform = 'translateY(0)';
    }, 10);
    
    // Remove after 3 seconds
    setTimeout(() => {
        toast.style.transform = 'translateY(full)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    // Bind the HTML toggle button
    const toggleRawBtn = document.getElementById('toggleRawBtn');
    if (toggleRawBtn) {
        toggleRawBtn.addEventListener('click', toggleHtmlMode);
    }
    
    // Make functions globally available
    window.toggleSourceEditMode = toggleSourceEditMode;
    window.saveSourceEdit = saveSourceEdit;
    window.cancelSourceEdit = cancelSourceEdit;
});
