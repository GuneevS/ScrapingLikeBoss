// Global variables
let currentPage = 1;
let itemsPerPage = 50;
let allProducts = [];
let filteredProducts = [];
let selectedProducts = new Set();
let currentModalSku = '';

// Load products on page load
document.addEventListener('DOMContentLoaded', function() {
    // Ensure modal is closed on page load
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = 'none';
    }
    
    // Reset modal state
    currentModalSku = '';
    
    // Load products and filters
    loadProducts();
    loadFilterOptions();
    
    // Add click handler to close modal when clicking outside
    const imageModal = document.getElementById('imageModal');
    if (imageModal) {
        imageModal.addEventListener('click', function(e) {
            if (e.target === imageModal) {
                closeModal();
            }
        });
    }
});

// Load all products
async function loadProducts() {
    showLoading(true);
    try {
        const response = await apiCall('/api/products/all');
        allProducts = response.products;
        applyFilters();
        updateStatistics();
    } catch (error) {
        showAlert('Failed to load products: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// Load filter options
async function loadFilterOptions() {
    try {
        const response = await apiCall('/api/products/filters');
        
        // Populate brand filter
        const brandSelect = document.getElementById('filter-brand');
        response.brands.forEach(brand => {
            if (brand) {
                const option = document.createElement('option');
                option.value = brand;
                option.textContent = brand;
                brandSelect.appendChild(option);
            }
        });
        
        // Populate tier1 filter
        const tier1Select = document.getElementById('filter-tier1');
        response.tier1s.forEach(tier => {
            if (tier) {
                const option = document.createElement('option');
                option.value = tier;
                option.textContent = tier;
                tier1Select.appendChild(option);
            }
        });
    } catch (error) {
        console.error('Failed to load filter options:', error);
    }
}

// Apply filters
function applyFilters() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const statusFilter = document.getElementById('filter-status').value;
    const clipFilter = document.getElementById('filter-clip').value;
    const brandFilter = document.getElementById('filter-brand').value;
    const tierFilter = document.getElementById('filter-tier1').value;
    const hasImageFilter = document.getElementById('filter-has-image').value;
    const confidenceFilter = document.getElementById('filter-confidence').value;
    
    filteredProducts = allProducts.filter(product => {
        // Search filter
        if (searchTerm) {
            const searchableText = `${product.Variant_SKU} ${product.Title} ${product.Brand} ${product.Variant_Barcode}`.toLowerCase();
            if (!searchableText.includes(searchTerm)) return false;
        }
        
        // Status filter
        if (statusFilter && product.image_status !== statusFilter) return false;
        
        // CLIP filter
        if (clipFilter) {
            if (clipFilter === 'not_validated' && product.clip_action) return false;
            if (clipFilter !== 'not_validated' && product.clip_action !== clipFilter) return false;
        }
        
        // Brand filter
        if (brandFilter && product.Brand !== brandFilter) return false;
        
        // Tier1 filter
        if (tierFilter && product.Tier_1 !== tierFilter) return false;
        
        // Has image filter
        if (hasImageFilter === 'yes' && !product.downloaded_image_path) return false;
        if (hasImageFilter === 'no' && product.downloaded_image_path) return false;
        
        // Confidence filter
        const confidence = product.confidence || 0;
        if (confidenceFilter === 'high' && confidence <= 80) return false;
        if (confidenceFilter === 'medium' && (confidence < 50 || confidence > 80)) return false;
        if (confidenceFilter === 'low' && confidence >= 50) return false;
        
        return true;
    });
    
    currentPage = 1;
    renderProducts();
}

// Clear filters
function clearFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-clip').value = '';
    document.getElementById('filter-brand').value = '';
    document.getElementById('filter-tier1').value = '';
    document.getElementById('filter-has-image').value = '';
    document.getElementById('filter-confidence').value = '';
    applyFilters();
}

// Render products table
function renderProducts() {
    const tbody = document.getElementById('products-tbody');
    tbody.innerHTML = '';
    
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const productsToShow = filteredProducts.slice(startIndex, endIndex);
    
    productsToShow.forEach(product => {
        const tr = document.createElement('tr');
        tr.dataset.sku = product.Variant_SKU;
        
        // Format product name (combine Title and Variant)
        const productName = product.Variant_Title ? 
            `${product.Title} - ${product.Variant_Title}` : 
            product.Title || '';
        
        // Format source information
        let sourceInfo = '-';
        if (product.image_source && product.image_source !== 'manually approved') {
            // Extract domain from URL if it's a full URL
            try {
                const url = new URL(product.image_source);
                sourceInfo = `<a href="${product.image_source}" target="_blank" title="${product.image_source}">${url.hostname}</a>`;
            } catch {
                sourceInfo = product.source_retailer || product.image_source || '-';
            }
        } else if (product.source_retailer) {
            sourceInfo = product.source_retailer;
        }
        
        // Format CLIP analysis with details
        let clipInfo = '-';
        if (product.clip_confidence) {
            const clipScore = Math.round(product.clip_confidence * 100);
            const clipIcon = product.clip_action === 'auto_reject' ? '❌' : 
                            product.clip_action === 'manual_review' ? '⚠️' : 
                            product.clip_action === 'auto_approve' ? '✅' : '';
            
            const clipDetails = [];
            if (product.detected_text) clipDetails.push(`Text: ${product.detected_text.substring(0, 50)}...`);
            if (product.clip_validation) clipDetails.push(product.clip_validation);
            if (product.ocr_match) clipDetails.push('OCR Match ✓');
            
            clipInfo = `
                <div class="clip-analysis">
                    <span class="clip-score ${product.clip_action || ''}">
                        ${clipScore}% ${clipIcon}
                    </span>
                    ${clipDetails.length > 0 ? 
                        `<div class="clip-details" title="${clipDetails.join(' | ')}">
                            <small>${clipDetails[0]}</small>
                        </div>` : ''}
                </div>
            `;
        }
        
        tr.innerHTML = `
            <td>
                <input type="checkbox" class="product-checkbox" data-sku="${product.Variant_SKU}">
            </td>
            <td class="image-cell">
                ${product.downloaded_image_path ? 
                    `<img src="/image/${product.Variant_SKU}" class="product-thumbnail" onclick="previewImage('${product.Variant_SKU}')" onerror="this.src='/static/images/no-image.png'" alt="${productName}">` : 
                    '<span class="no-image">No image</span>'}
            </td>
            <td class="sku-cell">${product.Variant_SKU}</td>
            <td class="product-name" title="${productName}">${productName}</td>
            <td>${product.Brand || ''}</td>
            <td>${product.Tier_1 || ''}</td>
            <td>
                <span class="status-badge status-${product.image_status || 'not_processed'}">
                    ${product.image_status || 'not processed'}
                </span>
            </td>
            <td class="clip-cell">${clipInfo}</td>
            <td class="source-cell">${sourceInfo}</td>
            <td class="actions-cell">
                ${product.image_status === 'pending' ? 
                    `<button class="btn btn-success btn-sm action-btn" onclick="approveProduct('${product.Variant_SKU}')">✓ Approve</button>
                     <button class="btn btn-danger btn-sm action-btn" onclick="declineProduct('${product.Variant_SKU}')">✗ Decline</button>` :
                product.image_status === 'approved' ?
                    `<button class="btn btn-warning btn-sm action-btn" onclick="unapproveProduct('${product.Variant_SKU}')">↶ Unapprove</button>
                     <button class="btn btn-secondary btn-sm action-btn" onclick="reprocessProduct('${product.Variant_SKU}')">🔄 Reprocess</button>` :
                product.image_status === 'not_processed' ?
                    `<button class="btn btn-primary btn-sm action-btn" id="process-${product.Variant_SKU}" onclick="processProduct('${product.Variant_SKU}')">⚡ Process</button>` :
                product.image_status === 'declined' ?
                    `<button class="btn btn-success btn-sm action-btn" onclick="approveProduct('${product.Variant_SKU}')">✓ Approve</button>
                     <button class="btn btn-secondary btn-sm action-btn" onclick="reprocessProduct('${product.Variant_SKU}')">🔄 Reprocess</button>` :
                    `<button class="btn btn-secondary btn-sm action-btn" onclick="reprocessProduct('${product.Variant_SKU}')">🔄 Reprocess</button>`}
            </td>
        `;
        tbody.appendChild(tr);
    });
    
    renderPagination();
    updateBulkActionsBar();
}

// Render pagination
function renderPagination() {
    const totalPages = Math.ceil(filteredProducts.length / itemsPerPage);
    const pagination = document.getElementById('pagination');
    pagination.innerHTML = '';
    
    // Previous button
    const prevBtn = document.createElement('button');
    prevBtn.textContent = 'Previous';
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = () => {
        if (currentPage > 1) {
            currentPage--;
            renderProducts();
        }
    };
    pagination.appendChild(prevBtn);
    
    // Page numbers
    for (let i = 1; i <= Math.min(totalPages, 10); i++) {
        const pageBtn = document.createElement('button');
        pageBtn.textContent = i;
        pageBtn.className = i === currentPage ? 'active' : '';
        pageBtn.onclick = () => {
            currentPage = i;
            renderProducts();
        };
        pagination.appendChild(pageBtn);
    }
    
    // Next button
    const nextBtn = document.createElement('button');
    nextBtn.textContent = 'Next';
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.onclick = () => {
        if (currentPage < totalPages) {
            currentPage++;
            renderProducts();
        }
    };
    pagination.appendChild(nextBtn);
    
    // Page info
    const pageInfo = document.createElement('span');
    pageInfo.textContent = ` Page ${currentPage} of ${totalPages} (${filteredProducts.length} products)`;
    pageInfo.style.marginLeft = '1rem';
    pagination.appendChild(pageInfo);
}

// Update statistics
function updateStatistics() {
    const stats = {
        total: allProducts.length,
        approved: allProducts.filter(p => p.image_status === 'approved').length,
        pending: allProducts.filter(p => p.image_status === 'pending').length,
        declined: allProducts.filter(p => p.image_status === 'declined').length,
        notprocessed: allProducts.filter(p => p.image_status === 'not_processed').length
    };
    
    document.getElementById('stat-total').textContent = stats.total;
    document.getElementById('stat-approved').textContent = stats.approved;
    document.getElementById('stat-pending').textContent = stats.pending;
    document.getElementById('stat-declined').textContent = stats.declined;
    document.getElementById('stat-notprocessed').textContent = stats.notprocessed;
}

// Toggle selection
function toggleSelection(sku) {
    if (selectedProducts.has(sku)) {
        selectedProducts.delete(sku);
    } else {
        selectedProducts.add(sku);
    }
    updateBulkActionsBar();
}

// Toggle select all
function toggleSelectAll() {
    const checkbox = document.getElementById('select-all');
    if (checkbox.checked) {
        filteredProducts.forEach(p => selectedProducts.add(p.Variant_SKU));
    } else {
        selectedProducts.clear();
    }
    renderProducts();
}

// Update bulk actions bar
function updateBulkActionsBar() {
    const bar = document.getElementById('bulk-actions-bar');
    const count = document.getElementById('selected-count');
    
    if (selectedProducts.size > 0) {
        bar.classList.add('active');
        count.textContent = selectedProducts.size;
    } else {
        bar.classList.remove('active');
    }
}

// Clear selection
function clearSelection() {
    selectedProducts.clear();
    document.getElementById('select-all').checked = false;
    renderProducts();
}

// Show/hide loading
function showLoading(show) {
    const overlay = document.getElementById('loading-overlay');
    if (show) {
        overlay.classList.add('active');
    } else {
        overlay.classList.remove('active');
    }
}

// Preview image
function previewImage(sku) {
    // Validate SKU and product existence
    if (!sku) {
        console.error('No SKU provided to previewImage');
        return;
    }
    
    const product = allProducts.find(p => p.Variant_SKU === sku);
    if (!product) {
        showAlert(`Product with SKU ${sku} not found`, 'error');
        return;
    }
    
    if (!product.downloaded_image_path) {
        showAlert(`No image available for ${sku}`, 'warning');
        return;
    }
    
    // Set modal state
    currentModalSku = sku;
    
    // Update modal content
    const modalTitle = document.getElementById('modalTitle');
    const modalImage = document.getElementById('modalImage');
    const modalInfo = document.getElementById('modalInfo');
    
    if (modalTitle) modalTitle.textContent = product.Title || 'Unknown Product';
    if (modalImage) {
        modalImage.src = `/image/${sku}`;
        modalImage.alt = product.Title || 'Product Image';
        modalImage.onerror = function() {
            showAlert('Failed to load image', 'error');
            closeModal();
        };
    }
    
    let info = `
        <p><strong>SKU:</strong> ${product.Variant_SKU}</p>
        <p><strong>Brand:</strong> ${product.Brand || 'Unknown'}</p>
        <p><strong>Status:</strong> ${product.image_status || 'Unknown'}</p>
        <p><strong>Confidence:</strong> ${product.confidence ? Math.round(product.confidence) + '%' : 'N/A'}</p>
        <p><strong>Tier 1:</strong> ${product.Tier_1 || 'N/A'}</p>
        <p><strong>Tier 2:</strong> ${product.Tier_2 || 'N/A'}</p>
    `;
    
    if (product.clip_confidence) {
        info += `<p><strong>CLIP Score:</strong> ${Math.round(product.clip_confidence * 100)}%</p>`;
        info += `<p><strong>CLIP Action:</strong> ${product.clip_action || 'N/A'}</p>`;
    }
    
    if (modalInfo) modalInfo.innerHTML = info;
    
    // Show modal
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

// Close modal
function closeModal() {
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = 'none';
    }
    
    // Reset modal state
    currentModalSku = '';
    
    // Clear modal content to prevent old data showing
    const modalImage = document.getElementById('modalImage');
    const modalInfo = document.getElementById('modalInfo');
    const modalTitle = document.getElementById('modalTitle');
    
    if (modalImage) modalImage.src = '';
    if (modalInfo) modalInfo.innerHTML = '';
    if (modalTitle) modalTitle.textContent = 'Product Image';
}

// Approve from modal
async function approveFromModal() {
    if (!currentModalSku) {
        showAlert('No product selected in modal', 'error');
        return;
    }
    
    try {
        await approveProduct(currentModalSku);
        closeModal();
    } catch (error) {
        showAlert('Failed to approve product: ' + error.message, 'error');
    }
}

// Decline from modal
async function declineFromModal() {
    if (!currentModalSku) {
        showAlert('No product selected in modal', 'error');
        return;
    }
    
    try {
        await declineProduct(currentModalSku);
        closeModal();
    } catch (error) {
        showAlert('Failed to decline product: ' + error.message, 'error');
    }
}

// Individual product actions
async function approveProduct(sku) {
    if (!sku) {
        showAlert('No SKU provided for approval', 'error');
        return;
    }
    
    const button = event?.target;
    if (button) setButtonLoading(button, true);
    
    try {
        const result = await apiCall(`/api/approve/${sku}`, 'POST');
        showAlert(`Product ${sku} approved successfully`, 'success');
        await loadProducts();
    } catch (error) {
        showAlert('Failed to approve: ' + error.message, 'error');
        if (button) setButtonLoading(button, false);
    } finally {
        if (button) setTimeout(() => setButtonLoading(button, false), 1000);
    }
}

async function declineProduct(sku) {
    if (!sku) {
        showAlert('No SKU provided for decline', 'error');
        return;
    }
    
    const button = event?.target;
    if (button) setButtonLoading(button, true);
    
    try {
        const result = await apiCall(`/api/decline/${sku}`, 'POST');
        showAlert(`Product ${sku} declined successfully`, 'warning');
        await loadProducts();
    } catch (error) {
        showAlert('Failed to decline: ' + error.message, 'error');
        if (button) setButtonLoading(button, false);
    } finally {
        if (button) setTimeout(() => setButtonLoading(button, false), 1000);
    }
}

async function unapproveProduct(sku) {
    const button = event.target;
    
    confirmAction(`Unapprove product ${sku}? This will move it back to pending status.`, async () => {
        setButtonLoading(button, true);
        
        try {
            const response = await fetch(`/api/product/${sku}/status`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ status: 'pending' })
            });
            
            const result = await response.json();
            
            if (result.success) {
                showAlert(`Product ${sku} moved to pending`, 'success');
                await loadProducts();
            } else {
                showAlert(result.message || 'Failed to unapprove product', 'error');
            }
        } catch (error) {
            showAlert('Error: ' + error.message, 'error');
        } finally {
            setButtonLoading(button, false);
        }
    }, {
        title: 'Unapprove Product',
        confirmText: 'Unapprove' 
    });
}

// Process product (for not_processed status)
async function processProduct(sku) {
    if (!sku) {
        showAlert('No SKU provided for processing', 'error');
        return;
    }
    
    const button = event?.target;
    if (button) setButtonLoading(button, true);
    
    try {
        const result = await apiCall('/api/process', 'POST', {
            skus: [sku]
        });
        
        if (result.success) {
            showAlert(`Processing started for ${sku}`, 'success');
            // Reload products after a delay to see updated status
            setTimeout(() => loadProducts(), 3000);
        } else {
            showAlert(result.message || 'Processing failed', 'error');
        }
    } catch (error) {
        showAlert('Processing failed: ' + error.message, 'error');
        if (button) setButtonLoading(button, false);
    } finally {
        if (button) setTimeout(() => setButtonLoading(button, false), 2000);
    }
}

// Reprocess product (for processed products)
async function reprocessProduct(sku) {
    if (!sku) {
        showAlert('No SKU provided for reprocessing', 'error');
        return;
    }
    
    const button = event?.target;
    
    confirmAction(`Reprocess product ${sku}? This will search for a new image.`, async () => {
        if (button) setButtonLoading(button, true);
        showAlert(`Starting reprocessing for ${sku}...`, 'info', 3000);
        
        try {
            const result = await apiCall(`/api/reprocess/${sku}`, 'POST');
            
            if (result.success) {
                showAlert(`Reprocessing completed for ${sku}`, 'success');
                setTimeout(() => loadProducts(), 2000);
            } else {
                showAlert(result.message || 'Reprocess failed', 'error');
            }
        } catch (error) {
            showAlert('Reprocess failed: ' + error.message, 'error');
        } finally {
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'Reprocess Product',
        confirmText: 'Reprocess'
    });
}

// Bulk actions
async function bulkApprove() {
    const button = document.querySelector('[onclick="bulkApprove()"]');
    
    confirmAction(`Approve ${selectedProducts.size} products?`, async () => {
        if (button) setButtonLoading(button, true);
        showAlert(`Starting bulk approval of ${selectedProducts.size} products...`, 'info', 3000);
        
        try {
            await apiCall('/api/bulk-action', 'POST', {
                action: 'approve',
                skus: Array.from(selectedProducts)
            });
            
            showAlert(`Approved ${selectedProducts.size} products successfully`, 'success');
            clearSelection();
            await loadProducts();
        } catch (error) {
            showAlert('Bulk approve failed: ' + error.message, 'error');
        } finally {
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'Bulk Approve',
        confirmText: 'Approve All'
    });
}

async function bulkDecline() {
    const button = document.querySelector('[onclick="bulkDecline()"]');
    
    confirmAction(`Decline ${selectedProducts.size} products?`, async () => {
        if (button) setButtonLoading(button, true);
        showAlert(`Starting bulk decline of ${selectedProducts.size} products...`, 'info', 3000);
        
        try {
            await apiCall('/api/bulk-action', 'POST', {
                action: 'decline',
                skus: Array.from(selectedProducts)
            });
            
            showAlert(`Declined ${selectedProducts.size} products successfully`, 'warning');
            clearSelection();
            await loadProducts();
        } catch (error) {
            showAlert('Bulk decline failed: ' + error.message, 'error');
        } finally {
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'Bulk Decline',
        confirmText: 'Decline All'
    });
}

async function bulkReprocess() {
    const button = document.querySelector('[onclick="bulkReprocess()"]');
    
    confirmAction(`Reprocess ${selectedProducts.size} products? This may take a while.`, async () => {
        if (button) setButtonLoading(button, true);
        showLoading(true);
        showAlert(`Starting bulk reprocessing of ${selectedProducts.size} products...`, 'info', 5000);
        
        try {
            let processed = 0;
            let failed = 0;
            
            for (const sku of selectedProducts) {
                try {
                    const result = await apiCall(`/api/reprocess/${sku}`, 'POST');
                    if (result.success) {
                        processed++;
                    } else {
                        failed++;
                    }
                } catch (error) {
                    failed++;
                }
            }
            
            showAlert(`Reprocessed: ${processed} success, ${failed} failed`, processed > 0 ? 'success' : 'warning');
            clearSelection();
            await loadProducts();
        } catch (error) {
            showAlert('Bulk reprocess failed: ' + error.message, 'error');
        } finally {
            showLoading(false);
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'Bulk Reprocess',
        confirmText: 'Reprocess All'
    });
}

async function bulkValidateCLIP() {
    const button = document.querySelector('[onclick="bulkValidateCLIP()"]');
    
    confirmAction(`Run CLIP validation on ${selectedProducts.size} selected products?`, async () => {
        if (button) setButtonLoading(button, true);
        showLoading(true);
        showAlert(`Starting CLIP validation for ${selectedProducts.size} products...`, 'info', 3000);
        
        try {
            const skus = Array.from(selectedProducts);
            await apiCall('/api/validate-images', 'POST', {
                skus: skus,
                validate_all: false
            });
            
            showAlert('CLIP validation completed successfully', 'success');
            clearSelection();
            await loadProducts();
        } catch (error) {
            showAlert('Validation failed: ' + error.message, 'error');
        } finally {
            showLoading(false);
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'CLIP Validation',
        confirmText: 'Validate'
    });
}

async function bulkApproveHighCLIP() {
    const button = document.querySelector('[onclick="bulkApproveHighCLIP()"]');
    
    confirmAction('Auto-approve all products with CLIP score > 60%?', async () => {
        if (button) setButtonLoading(button, true);
        showLoading(true);
        showAlert('Analyzing products with high CLIP scores...', 'info', 3000);
        
        try {
            const highScoreProducts = allProducts.filter(p => 
                p.clip_confidence && p.clip_confidence > 0.6 && p.image_status === 'pending'
            );
            
            if (highScoreProducts.length === 0) {
                showAlert('No pending products with CLIP score > 60%', 'warning');
                return;
            }
            
            const skus = highScoreProducts.map(p => p.Variant_SKU);
            await apiCall('/api/bulk-action', 'POST', {
                action: 'approve',
                skus: skus
            });
            
            showAlert(`Approved ${skus.length} products with high CLIP scores`, 'success');
            await loadProducts();
        } catch (error) {
            showAlert('Bulk approve failed: ' + error.message, 'error');
        } finally {
            showLoading(false);
            if (button) setButtonLoading(button, false);
        }
    }, {
        title: 'Auto-Approve High CLIP Scores',
        confirmText: 'Auto-Approve'
    });
}

async function exportSelected() {
    if (selectedProducts.size === 0) {
        showAlert('No products selected', 'warning');
        return;
    }
    
    try {
        const response = await apiCall('/api/export/selected', 'POST', {
            skus: Array.from(selectedProducts)
        });
        
        if (response.file_path) {
            window.location.href = response.file_path;
            showAlert('Export complete', 'success');
        }
    } catch (error) {
        showAlert('Export failed: ' + error.message, 'error');
    }
}
