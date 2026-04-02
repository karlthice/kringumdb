/**
 * api.js - API client for KringumDB Flask backend
 */
var API = {
    async call(endpoint, data) {
        data = data || {};
        var response = await fetch('/api/' + endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return response.json();
    },

    async get(endpoint) {
        var response = await fetch('/api/' + endpoint);
        return response.json();
    }
};
