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
function showAlert(message, type = 'success', duration = 5000) {
    console.log(`Alert: ${type} - ${message}`);
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;
    
    // Add close button
    const closeBtn = document.createElement('span');
    closeBtn.innerHTML = '&times;';
    closeBtn.style.cssText = 'float: right; cursor: pointer; font-size: 1.2em; margin-left: 10px;';
    closeBtn.onclick = () => alertDiv.remove();
    alertDiv.appendChild(closeBtn);
    
    const container = document.querySelector('.container');
    if (container) {
        container.insertBefore(alertDiv, container.firstChild);
        
        // Auto-remove after duration
        setTimeout(() => {
            if (alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, duration);
    } else {
        console.warn('Container not found for alert display');
        alert(message); // Fallback
    }
}

// Enhanced confirmation
function confirmAction(message) {
    return confirm(message);
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
    showAlert('An unexpected error occurred: ' + event.reason.message, 'error');
});

// Global error handler
window.addEventListener('error', function(event) {
    console.error('JavaScript error:', event.error);
    if (event.error.message.includes('apiCall')) {
        showAlert('JavaScript function error detected. Please refresh the page.', 'error');
    }
});
