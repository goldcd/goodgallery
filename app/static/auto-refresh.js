// Auto-refresh UI when file changes are detected
(function() {
    let lastFileCount = parseInt(document.querySelector('.stats').textContent.match(/(\d+)\s+images/)[1]);
    
    async function checkForChanges() {
        try {
            const response = await fetch('/api/stats');
            const data = await response.json();
            
            if (data.total !== lastFileCount) {
                // File count changed - reload page
                console.log(`File count changed: ${lastFileCount} → ${data.total}`);
                window.location.reload();
            }
        } catch (e) {
            console.error('Failed to check for changes:', e);
        }
    }
    
    // Check for changes every 5 seconds
    setInterval(checkForChanges, 5000);
})();
