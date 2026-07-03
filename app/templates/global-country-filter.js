// Global Country Filter Management
// This script handles admin-level country filtering across all pages

(function() {
    const STORAGE_KEY = 'admin_country_filter';
    
    // Load saved country immediately and expose globally
    const savedCountry = localStorage.getItem(STORAGE_KEY) || '';
    window.adminCountryFilter = savedCountry;
    
    // Sync the global filter with page-specific filters
    function syncPageFilters(country) {
        const pageFilters = [
            'country-filter',           // vehicles
            'fines-country-filter',     // fines
            'stats-country-filter',     // fines_stats
            'payments-country-filter',  // payments
            'dashboard-country-filter', // dashboard
            'report-country',           // reports
            'phones-country-filter',    // phones
            'usage-country-filter',     // phone_usage
            'filter-country'            // photo_submissions
        ];
        
        pageFilters.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.value = country;
            }
        });
    }
    
    // Get the current global country filter
    function getGlobalCountryFilter() {
        return window.adminCountryFilter || localStorage.getItem(STORAGE_KEY) || '';
    }
    
    // Inject global country filter into fetch requests
    // This intercepts fetch calls and adds country parameter
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const country = getGlobalCountryFilter();
        if (!country) {
            return originalFetch.apply(this, args);
        }
        
        let url = args[0];
        if (typeof url === 'string') {
            // Add country parameter to API calls
            if (url.includes('/api/') && !url.includes('country=')) {
                const separator = url.includes('?') ? '&' : '?';
                url = url + separator + 'country=' + encodeURIComponent(country);
                args[0] = url;
            }
        }
        
        return originalFetch.apply(this, args);
    };
    
    // Initialize global country filter (admin only)
    function initGlobalCountryFilter() {
        const globalFilter = document.getElementById('global-country-filter');
        if (!globalFilter) return; // Not admin page
        
        // Set the global filter to saved value
        globalFilter.value = savedCountry;
        
        // Listen for changes
        globalFilter.addEventListener('change', function() {
            const country = this.value;
            localStorage.setItem(STORAGE_KEY, country);
            window.adminCountryFilter = country;
            
            // Sync with page-specific filters if they exist
            syncPageFilters(country);
            
            // Reload current page to apply new filter
            window.location.reload();
        });
    }
    
    // Initialize on page load
    document.addEventListener('DOMContentLoaded', initGlobalCountryFilter);
    
    // Also sync page filters on DOMContentLoaded if they exist
    document.addEventListener('DOMContentLoaded', function() {
        syncPageFilters(savedCountry);
    });
})();
