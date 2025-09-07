/**
 * NWK Image Management System - Common JavaScript Functions
 * Fixes ReferenceError and provides enhanced functionality
 */

// Ensure apiCall function is available globally with multiple assignment methods
async function apiCall(url, method = 'GET', data = null) {
    console.log(`API Call: ${method} ${url}`, data);
    
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json'
        }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, options);
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        
        return result;
    } catch (error) {
        console.error('API Call Error:', error);
        throw error;
    }
}

// Enhanced alert system - define before exposing to global scope
function showAlert(message, type = 'info', duration = 5000, options = {}) {
    const alertsContainer = document.getElementById('alerts-container') || createAlertsContainer();
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    
    // Add icon based on type
    const icons = {
        'success': '✓',
        'error': '✗',
        'warning': '⚠',
        'info': 'ℹ'
    };
    
    const icon = icons[type] || icons['info'];
    
    alert.innerHTML = `
        <span class="alert-icon">${icon}</span>
        <span class="alert-message">${message}</span>
        ${!options.persistent ? '<button type="button" class="btn-close" aria-label="Close"></button>' : ''}
    `;
    
    alertsContainer.appendChild(alert);
    
    // Auto-dismiss after duration (unless persistent)
    if (!options.persistent && duration > 0) {
        setTimeout(() => {
            if (alert.parentNode) {
                alert.classList.add('fade-out');
                setTimeout(() => alert.remove(), 300);
            }
        }, duration);
    }
    
    // Manual dismiss
    const closeBtn = alert.querySelector('.btn-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            alert.classList.add('fade-out');
            setTimeout(() => alert.remove(), 300);
        });
    }
    
    return alert; // Return reference for manual control
}

// Enhanced confirmation
function confirmAction(message, callback, options = {}) {
    // Create custom confirmation modal instead of native confirm
    const modal = document.createElement('div');
    modal.className = 'confirmation-modal-overlay';
    modal.innerHTML = `
        <div class="confirmation-modal">
            <div class="confirmation-content">
                <h3>${options.title || 'Confirm Action'}</h3>
                <p>${message}</p>
                <div class="confirmation-buttons">
                    <button class="btn btn-secondary" id="confirmCancel">Cancel</button>
                    <button class="btn btn-danger" id="confirmOk">${options.confirmText || 'Confirm'}</button>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add event listeners
    const confirmBtn = modal.querySelector('#confirmOk');
    const cancelBtn = modal.querySelector('#confirmCancel');
    
    const cleanup = () => {
        document.body.removeChild(modal);
    };
    
    confirmBtn.addEventListener('click', () => {
        cleanup();
        callback();
    });
    
    cancelBtn.addEventListener('click', cleanup);
    
    // Close on overlay click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            cleanup();
        }
    });
    
    // Focus on confirm button
    setTimeout(() => confirmBtn.focus(), 100);
}

// Debug helper
function debugLog(message, data = null) {
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
        console.log('[NWK Debug]', message, data);
    }
}

// Expose all functions to global scope immediately
window.apiCall = apiCall;
window.showAlert = showAlert;
window.confirmAction = confirmAction;
window.debugLog = debugLog;

// Also expose to globalThis for modern browsers
if (typeof globalThis !== 'undefined') {
    globalThis.apiCall = apiCall;
    globalThis.showAlert = showAlert;
    globalThis.confirmAction = confirmAction;
    globalThis.debugLog = debugLog;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    debugLog('Common JavaScript loaded');
    
    // Test API availability
    if (typeof apiCall !== 'function') {
        console.error('apiCall function not available!');
    } else {
        debugLog('apiCall function available');
    }
    
    // Test alert system
    debugLog('Alert system initialized');
});

// Error handling for unhandled promise rejections
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
    showAlert('An unexpected error occurred. Please refresh and try again.', 'error', 8000);
});

// Global error handler
window.addEventListener('error', function(event) {
    console.error('Global error:', event.error);
    showAlert('A JavaScript error occurred. Please refresh and try again.', 'error', 8000);
});

// Add utility function for loading states
window.setButtonLoading = function(button, loading = true, originalText = null) {
    if (loading) {
        button.dataset.originalText = originalText || button.textContent;
        button.textContent = 'Processing...';
        button.disabled = true;
        button.classList.add('btn-loading');
    } else {
        button.textContent = button.dataset.originalText || originalText || 'Process';
        button.disabled = false;
        button.classList.remove('btn-loading');
        delete button.dataset.originalText;
    }
};

// Add utility for progress tracking
window.createProgressTracker = function(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return null;
    
    return {
        show: () => container.style.display = 'block',
        hide: () => container.style.display = 'none',
        update: (percent, message) => {
            const progressBar = container.querySelector('.progress-bar');
            const progressText = container.querySelector('.progress-text');
            
            if (progressBar) {
                progressBar.style.width = `${percent}%`;
                progressBar.setAttribute('aria-valuenow', percent);
            }
            
            if (progressText && message) {
                progressText.textContent = message;
            }
        }
    };
};

// Helper function to create alerts container if it doesn't exist
function createAlertsContainer() {
    const container = document.createElement('div');
    container.id = 'alerts-container';
    document.body.appendChild(container);
    return container;
}
