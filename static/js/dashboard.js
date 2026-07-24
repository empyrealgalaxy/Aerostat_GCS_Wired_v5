class AerostatDashboard {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.isConnected = false;
        this.parameterConfig = {};
        this.currentScreen = 'primary';
        
        this.init();
    }

    init() {
        this.connectWebSocket();
        this.setupEventListeners();
        this.startPeriodicTasks();
        this.loadParameterConfig();
        
        // Add connection status indicator
        this.addConnectionIndicator();
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/sensor-data`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.updateSensorData(data);
                } catch (error) {
                    console.error('Error parsing WebSocket data:', error);
                }
            };
            
            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.isConnected = false;
                this.updateConnectionStatus(false);
            };
            
        } catch (error) {
            console.error('Failed to create WebSocket connection:', error);
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            setTimeout(() => {
                console.log(`Attempting to reconnect... (${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
                this.reconnectAttempts++;
                this.connectWebSocket();
            }, this.reconnectDelay * Math.pow(2, this.reconnectAttempts));
        }
    }

    updateSensorData(data) {
        // Update parameter values
        Object.keys(data).forEach(key => {
            const element = document.getElementById(key);
            if (element && key !== 'timestamp' && key !== 'mqtt_connected') {
                this.updateParameterElement(element, key, data[key]);
            }
        });

        // Update special elements
        this.updateSpecialElements(data);
        
        // Update last update timestamp
        if (data.timestamp) {
            this.updateTimestamp(data.timestamp);
        }

        // Check for threshold violations
        this.checkThresholds(data);
    }

    updateParameterElement(element, key, value) {
        let displayValue = value;
        let suffix = '';
        let className = 'parameter-value';

        // Determine suffix based on parameter type
        if (key.includes('temp')) {
            suffix = '°C';
        } else if (key.includes('degrees')) {
            suffix = '°';
        } else if (key.includes('pressure')) {
            suffix = ' mbar';
        } else if (key.includes('voltage')) {
            suffix = ' V';
        } else if (key.includes('current')) {
            suffix = ' A';
        } else if (key.includes('speed')) {
            suffix = ' m/s';
        } else if (key.includes('altitude') || key.includes('deployed')) {
            suffix = ' m';
        } else if (key.includes('tension') && key.includes('kg')) {
            suffix = ' kg';
        } else if (key.includes('tension') && key.includes('N')) {
            suffix = ' N';
        }

        // Format numeric values
        if (typeof value === 'number') {
            displayValue = value.toFixed(1);
        }

        // Check for threshold violations and update styling
        if (this.parameterConfig[key]) {
            const config = this.parameterConfig[key];
            if (typeof value === 'number' && config.enabled) {
                if (value < config.threshold_min || value > config.threshold_max) {
                    className += ' parameter-alert';
                    element.classList.add('alert-blink');
                } else {
                    element.classList.remove('alert-blink');
                }
            }
        }

        element.textContent = displayValue + suffix;
        element.className = className;

        // Update pressure gauges for specific parameters
        if (key === 'helium_pressure_mbar') {
            // Try to get min/max from DOM, fallback to config
            let min = 5.0, max = 20.0;
            const minEl = document.getElementById('helium_pressure_mbar_min_display');
            const maxEl = document.getElementById('helium_pressure_mbar_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawHeliumThermostatGauge === 'function') {
                drawHeliumThermostatGauge(value, min, max);
            }
        } else if (key === 'ballonet_pressure_mbar') {
            let min = 5.0, max = 20.0;
            const minEl = document.getElementById('ballonet_pressure_mbar_min_display');
            const maxEl = document.getElementById('ballonet_pressure_mbar_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawBallonetThermostatGauge === 'function') {
                drawBallonetThermostatGauge(value, min, max);
            }
        } else if (key === 'windscreen_pressure_mbar') {
            let min = 5.0, max = 20.0;
            const minEl = document.getElementById('windscreen_pressure_mbar_min_display');
            const maxEl = document.getElementById('windscreen_pressure_mbar_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawWindscreenThermostatGauge === 'function') {
                drawWindscreenThermostatGauge(value, min, max);
            }
        } else if (key === 'ambient_pressure_mbar') {
            let min = 5.0, max = 25.0;
            const minEl = document.getElementById('ambient_pressure_mbar_min_display');
            const maxEl = document.getElementById('ambient_pressure_mbar_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawAmbientThermostatGauge === 'function') {
                drawAmbientThermostatGauge(value, min, max);
            }
        } else if (key === 'confluence_point_tension_N') {
            let min = 5.0, max = 25.0;
            const minEl = document.getElementById('confluence_point_tension_N_min_display');
            const maxEl = document.getElementById('confluence_point_tension_N_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawConfluenceHalfDonutGauge === 'function') {
                drawConfluenceHalfDonutGauge(value, min, max);
            }
        } else if (key === 'winch_tether_tension_N') {
            let min = 5.0, max = 25.0;
            const minEl = document.getElementById('winch_tether_tension_N_min_display');
            const maxEl = document.getElementById('winch_tether_tension_N_max_display');
            if (minEl && maxEl) {
                const minVal = parseFloat(minEl.textContent.replace(/[^\d.\-]/g, ''));
                const maxVal = parseFloat(maxEl.textContent.replace(/[^\d.\-]/g, ''));
                if (!isNaN(minVal)) min = minVal;
                if (!isNaN(maxVal)) max = maxVal;
            } else if (this.parameterConfig[key]) {
                min = this.parameterConfig[key].threshold_min;
                max = this.parameterConfig[key].threshold_max;
            }
            if (typeof drawWinchHalfDonutGauge === 'function') {
                drawWinchHalfDonutGauge(value, min, max);
            }
        }
    }

    updateSpecialElements(data) {
        // Update status indicators
        const statusElements = document.querySelectorAll('[id$="_status"]');
        statusElements.forEach(element => {
            const key = element.id;
            if (data[key]) {
                this.updateStatusElement(element, data[key]);
            }
        });

        // Update compass needles
        if (data.wind_direction_degrees !== undefined) {
            this.updateCompass('compass_needle', data.wind_direction_degrees);
        }
        
        if (data.ground_wind_direction_degrees !== undefined) {
            this.updateCompass('ground_compass_needle', data.ground_wind_direction_degrees);
        }

        // Update progress bars
        this.updateProgressBars(data);
    }

    updateStatusElement(element, status) {
        element.textContent = status.toUpperCase();
        
        // Remove existing status classes
        element.className = element.className.replace(/status-\w+/g, '');
        
        // Add appropriate status class
        if (status === 'ON' || status === 'Connected' || status === 'Latched' || status === 'Active') {
            element.classList.add('status-on');
        } else if (status === 'OFF' || status === 'Disconnected' || status === 'Unlatched' || status === 'Inactive') {
            element.classList.add('status-off');
        } else if (status === 'GOOD') {
            element.classList.add('status-good');
        } else if (status === 'WARNING' || status === 'CAUTION') {
            element.classList.add('status-warning');
        } else if (status === 'CRITICAL' || status === 'ERROR') {
            element.classList.add('status-critical');
        } else {
            element.classList.add('status-off');
        }
    }

    updateCompass(needleId, degrees) {
        const needle = document.getElementById(needleId);
        if (needle) {
            needle.style.transform = `translate(-50%, -100%) rotate(${degrees}deg)`;
        }
    }

    updateProgressBars(data) {
        // Update pressure progress bars
        this.updateProgressBar('helium_pressure_mbar', data.helium_pressure_mbar, 20);
        this.updateProgressBar('ballonet_pressure_mbar', data.ballonet_pressure_mbar, 20);
        this.updateProgressBar('windscreen_pressure_mbar', data.windscreen_pressure_mbar, 20);
        this.updateProgressBar('ambient_pressure_mbar', data.ambient_pressure_mbar, 25);
        
        // Update tension progress bars
        this.updateProgressBar('confluence_point_tension_N', data.confluence_point_tension_N, 25);
        this.updateProgressBar('winch_tether_tension_kg', data.winch_tether_tension_kg, 25);
    }

    updateProgressBar(paramKey, value, maxValue) {
        const progressElement = document.getElementById(paramKey);
        const valueElement = document.getElementById(paramKey + '_value');
        
        if (progressElement && value !== undefined) {
            const percentage = Math.min((value / maxValue) * 100, 100);
            progressElement.style.width = `${percentage}%`;
            
            // Add glow effect for high values
            if (percentage > 80) {
                progressElement.classList.add('glow-effect');
            } else {
                progressElement.classList.remove('glow-effect');
            }
        }
        
        if (valueElement && value !== undefined) {
            const config = this.parameterConfig[paramKey];
            const unit = config ? config.unit : '';
            valueElement.textContent = `${value.toFixed(1)} ${unit}`;
        }
    }

    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connection-indicator');
        if (indicator) {
            indicator.className = connected ? 'status-connected' : 'status-disconnected';
            indicator.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
        }
    }

    updateTimestamp(timestamp) {
        const timestampElements = document.querySelectorAll('.last-update');
        timestampElements.forEach(element => {
            element.textContent = `Last update: ${timestamp}`;
        });
    }

    checkThresholds(data) {
        const alerts = [];
        
        Object.keys(data).forEach(key => {
            if (this.parameterConfig[key] && typeof data[key] === 'number') {
                const config = this.parameterConfig[key];
                const value = data[key];
                
                if (config.enabled) {
                    if (value < config.threshold_min) {
                        alerts.push({
                            parameter: key,
                            value: value,
                            threshold: config.threshold_min,
                            type: 'min_violation',
                            severity: 'warning'
                        });
                    } else if (value > config.threshold_max) {
                        alerts.push({
                            parameter: key,
                            value: value,
                            threshold: config.threshold_max,
                            type: 'max_violation',
                            severity: 'critical'
                        });
                    }
                }
            }
        });

        if (alerts.length > 0) {
            this.handleAlerts(alerts);
        }
    }

    handleAlerts(alerts) {
        // Display alerts in console for now (can be enhanced with UI notifications)
        alerts.forEach(alert => {
            console.warn(`Threshold violation: ${alert.parameter} = ${alert.value} (${alert.type}: ${alert.threshold})`);
        });
        
        // Could add visual/audio alerts here
        this.showNotification(`${alerts.length} threshold violation(s) detected`, 'warning');
    }

    setupEventListeners() {
        // Toggle parameter visibility (admin only)
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('toggle-visibility')) {
                const parameter = e.target.dataset.parameter;
                this.toggleParameterVisibility(parameter);
            }
            
            if (e.target.classList.contains('control-btn')) {
                const device = e.target.dataset.device;
                const action = e.target.dataset.action;
                this.sendControlCommand(device, action);
            }
        });

        // Screen navigation
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('screen-nav')) {
                const screen = e.target.dataset.screen;
                this.switchScreen(screen);
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case '1':
                        e.preventDefault();
                        this.switchScreen('primary');
                        break;
                    case '2':
                        e.preventDefault();
                        this.switchScreen('secondary');
                        break;
                    case '3':
                        e.preventDefault();
                        this.switchScreen('controls');
                        break;
                }
            }
        });
    }

    toggleParameterVisibility(parameter) {
        fetch('/admin/toggle-parameter', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ parameter: parameter })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showNotification(`Parameter ${parameter} visibility toggled`, 'success');
                // Refresh the page or update the UI accordingly
                setTimeout(() => window.location.reload(), 1000);
            }
        })
        .catch(error => {
            console.error('Error toggling parameter visibility:', error);
            this.showNotification('Error toggling parameter visibility', 'error');
        });
    }

    sendControlCommand(device, action) {
        const command = {
            device: device,
            action: action,
            timestamp: new Date().toISOString()
        };

        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify(command));
            this.showNotification(`Command sent: ${device} ${action}`, 'info');
        } else {
            this.showNotification('WebSocket not connected', 'error');
        }
    }

    switchScreen(screenName) {
        if (screenName !== this.currentScreen) {
            this.currentScreen = screenName;
            window.location.href = screenName === 'primary' ? '/dashboard' : `/screen/${screenName}`;
        }
    }

    loadParameterConfig() {
        fetch('/api/parameter-config')
            .then(response => response.json())
            .then(config => {
                this.parameterConfig = config;
            })
            .catch(error => {
                console.error('Error loading parameter configuration:', error);
            });
    }

    addConnectionIndicator() {
        // Add connection status indicator to the page
        const indicator = document.createElement('div');
        indicator.id = 'connection-indicator';
        indicator.className = 'status-disconnected';
        indicator.textContent = 'DISCONNECTED';
        indicator.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            transition: all 0.3s ease;
        `;
        document.body.appendChild(indicator);
    }

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 70px;
            right: 20px;
            z-index: 1001;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.875rem;
            color: white;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            max-width: 300px;
            word-wrap: break-word;
        `;

        // Set background based on type
        switch(type) {
            case 'success':
                notification.style.background = 'linear-gradient(135deg, #22c55e 0%, #16a34a 100%)';
                break;
            case 'warning':
                notification.style.background = 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)';
                break;
            case 'error':
                notification.style.background = 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)';
                break;
            default:
                notification.style.background = 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)';
        }

        document.body.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.style.transform = 'translateX(0)';
        }, 100);

        // Animate out and remove
        setTimeout(() => {
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    startPeriodicTasks() {
        // Cleanup expired notifications every 30 seconds
        setInterval(() => {
            const notifications = document.querySelectorAll('.notification');
            notifications.forEach(notification => {
                if (Date.now() - parseInt(notification.dataset.created || '0') > 30000) {
                    notification.remove();
                }
            });
        }, 30000);

        // Refresh parameter config every 5 minutes
        setInterval(() => {
            this.loadParameterConfig();
        }, 300000);
    }
}

// Global functions for template usage
window.toggleParameter = function(param) {
    if (window.dashboard) {
        window.dashboard.toggleParameterVisibility(param);
    }
};

window.sendControlCommand = function(device, action) {
    if (window.dashboard) {
        window.dashboard.sendControlCommand(device, action);
    }
};

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.dashboard = new AerostatDashboard();
});

// Export for module usage if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AerostatDashboard;
}
