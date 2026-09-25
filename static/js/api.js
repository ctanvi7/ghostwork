/**
 * API client for GhostWork frontend
 */

const api = (() => {
    const BASE_URL = '/api';

    async function request(method, path, body = null) {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json'
            }
        };

        if (body) {
            options.body = JSON.stringify(body);
        }

        try {
            const response = await fetch(`${BASE_URL}${path}`, options);
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                throw new Error(`Server returned ${response.status} without JSON. Check the Flask server log.`);
            }
            const data = await response.json();

            if (!response.ok) {
                const error = new Error(data.error?.message || 'Request failed');
                error.status = response.status;
                error.code = data.error?.code;
                throw error;
            }

            return data;
        } catch (error) {
            if (error instanceof TypeError) {
                throw new Error('Network error');
            }
            throw error;
        }
    }

    return {
        getWorkflows() {
            return request('GET', '/workflows');
        },

        getWorkflow(id) {
            return request('GET', `/workflows/${id}`);
        },

        createExecution(data) {
            return request('POST', '/executions', data);
        },

        getExecution(id) {
            return request('GET', `/executions/${id}`);
        },

        approveExecution(approvalId) {
            return request('POST', `/approvals/${approvalId}/approve`);
        },

        rejectExecution(approvalId) {
            return request('POST', `/approvals/${approvalId}/reject`);
        },

        callApprover(executionId) {
            return request('POST', `/executions/${executionId}/call-approver`);
        }
    };
})();
