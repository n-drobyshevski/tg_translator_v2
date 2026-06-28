/* dashboard.js – renders dashboard charts */

let posts10dChart = null;
let posts10dChannelsChart = null;
let heatmapChart = null;
let throughputLatencyChart = null;

/* Build (or update) the chart */
function drawPosts10d({ labels, counts }) {
    const ctx = document.getElementById("chartPosts10d");
    if (!ctx) return;

    try {
        const chartConfig = {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "Posts per day",
                        data: counts,
                        fill: false,
                        tension: 0.3,
                        borderColor: '#3b82f6',
                        backgroundColor: '#3b82f6',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                    x: { ticks: { font: { size: 10 } } },
                },
                plugins: {
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: false,
                        backgroundColor: 'rgba(255, 255, 255, 0.98)',
                        titleColor: '#374151',
                        bodyColor: '#2563eb',
                        borderColor: 'rgba(226, 232, 240, 0.8)',
                        borderWidth: 1,
                        padding: 10,
                        boxPadding: 4,
                        cornerRadius: 8,
                        titleFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 13,
                            weight: 500
                        },
                        bodyFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 12,
                            weight: 500
                        },
                        boxWidth: 8,
                        boxHeight: 8,
                        usePointStyle: true,
                    },
                    legend: { display: false },
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false,
                },
            },
        };

        if (!posts10dChart) {
            posts10dChart = new Chart(ctx, chartConfig);
        } else {
            posts10dChart.data.labels = labels;
            posts10dChart.data.datasets[0].data = counts;
            posts10dChart.update('none');
        }
    } catch (error) {
        // Error handling can be added here if needed
    }
}

/* Build (or update) the channels chart */
function drawPosts10dChannels({ labels, series }) {
    const ctx = document.getElementById("chartPosts10dChannels");
    if (!ctx) return;

    try {
        if (posts10dChannelsChart) {
            posts10dChannelsChart.destroy();
        }

        const chartConfig = {
            type: "line",
            data: {
                labels,
                datasets: series.map((s, i) => ({
                    label: s.label,
                    data: s.data,
                    borderColor: getColor(i),
                    backgroundColor: getColor(i),
                    fill: false,
                    tension: 0,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: 2,
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                    x: { ticks: { font: { size: 10 } } },
                },
                plugins: {
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: false,
                        backgroundColor: 'rgba(255, 255, 255, 0.98)',
                        titleColor: '#374151',
                        bodyColor: '#2563eb',
                        borderColor: 'rgba(226, 232, 240, 0.8)',
                        borderWidth: 1,
                        padding: 10,
                        boxPadding: 4,
                        cornerRadius: 8,
                        titleFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 13,
                            weight: 500
                        },
                        bodyFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 12,
                            weight: 500
                        },
                        boxWidth: 8,
                        boxHeight: 8,
                        usePointStyle: true,
                    },
                    legend: { position: "top" },
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false,
                },
            },
        };

        posts10dChannelsChart = new Chart(ctx, chartConfig);
    } catch (error) {
        // Error handling can be added here if needed
    }
}

/* Build (or update) heatmap */
function drawHeatmap(matrix) {
    if (!matrix) return;
    const { data, xLabels, yLabels, max } = matrix;
    const ctx = document.getElementById("heatmapChart");
    if (!ctx) return;
    
    try {
        if (heatmapChart) {
            heatmapChart.destroy();
        }

        heatmapChart = new Chart(ctx, {
            type: "matrix",
            data: {
                datasets: [
                    {
                        data: data,
                        backgroundColor: (chartCtx) => {
                            const item = chartCtx.dataset.data[chartCtx.dataIndex];
                            const alpha = max ? item.v / max : 0;
                            return `rgba(59,130,246,${alpha})`;
                        },
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        hoverBackgroundColor: (chartCtx) => {
                            const item = chartCtx.dataset.data[chartCtx.dataIndex];
                            const alpha = max ? item.v / max : 0;
                            return `rgba(59,130,246,${Math.min(1, alpha + 0.2)})`;
                        },
                        width: ({ chart }) => (chart.chartArea || {}).width / 24 - 1 || 20,
                        height: ({ chart }) => (chart.chartArea || {}).height / 7 - 1 || 20,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: "category", labels: xLabels },
                    y: { type: "category", labels: yLabels, reverse: true },
                },
                interaction: {
                    mode: 'nearest',
                    intersect: true,
                },
                plugins: {
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: false,
                        backgroundColor: 'rgba(255, 255, 255, 0.98)',
                        titleColor: '#374151',
                        bodyColor: '#2563eb',
                        borderColor: 'rgba(226, 232, 240, 0.8)',
                        borderWidth: 1,
                        padding: 10,
                        boxPadding: 4,
                        cornerRadius: 8,
                        displayColors: false,
                        callbacks: {
                            title: (items) => {
                                if (!items.length) return '';
                                const item = items[0];
                                const data = item.dataset.data[item.dataIndex];
                                if (data && typeof data.h !== 'undefined' && typeof data.d !== 'undefined') {
                                    const weekDays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
                                    const day = weekDays[data.d];
                                    const hour = data.h.toString().padStart(2, '0');
                                    return `${day} ${hour}:00`;
                                }
                                return item.label || '';
                            },
                            label: (item) => {
                                const data = item.dataset.data[item.dataIndex];
                                if (data && typeof data.v !== 'undefined') {
                                    return `${data.v} posts`;
                                }
                                return `${item.formattedValue} posts`;
                            }
                        },
                        titleFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 13,
                            weight: 500
                        },
                        bodyFont: {
                            family: "'Roboto', system-ui, -apple-system, sans-serif",
                            size: 12,
                            weight: 500
                        },
                        boxWidth: 8,
                        boxHeight: 8,
                        usePointStyle: true,
                        caretSize: 6,
                        caretPadding: 2
                    },
                    legend: { display: false },
                },
                animation: {
                    duration: 100
                },
            },
        });
    } catch (error) {
        // Error handling can be added here if needed
    }
}

function getColor(i) {
    const palette = [
        "#3b82f6",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#8b5cf6",
        "#14b8a6",
    ];
    return palette[i % palette.length];
}

/* Fetch summary JSON and feed the charts */
async function loadMetrics() {
    try {
        showLoadingState(true);
        const includeTest = getIncludeTestChannels();
        const res = await fetch(`/api/metrics/summary?include_test_channels=${includeTest ? "1" : "0"}`);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        
        const json = await res.json();
        
        if (json.posts_10d) {
            drawPosts10d(json.posts_10d);
        }
        
        if (json.throughput_latency) {
            drawThroughputLatency(json.throughput_latency);
        }

        if (json.posts_10d_channels) {
            drawPosts10dChannels(json.posts_10d_channels);
        }
        
        if (json.posts_matrix) {
            drawHeatmap(json.posts_matrix);
        }
        
        updateToggleState(includeTest);
        showLoadingState(false);
    } catch (error) {
        console.error('Failed to load metrics:', error);
        showErrorState(error.message);
        showLoadingState(false);
    }
}

// Initialize the time range slider
function initializeTimeRangeSlider() {
    const slider = document.getElementById("horizontal-slider");
    if (!slider) return;
    
    noUiSlider.create(slider, {
        start: 10,
        orientation: "horizontal",
        direction: "ltr",
        range: { min: 3, max: 30 },
        step: 1,
        connect: [true, false],
        tooltips: false,
        format: {
            to: (value) => Math.round(value),
            from: (value) => Number(value),
        },
    });

    slider.noUiSlider.on("update", function (values, handle) {
        document.getElementById("timeRangeValue").innerText = values[handle];
        document.getElementById("timeRangeDays").value = values[handle];
        if (typeof loadPostsPerChannelChart === "function") {
            loadPostsPerChannelChart(Number(values[handle]));
        }
    });
}

// Handle chart container scrollbar visibility
function initializeScrollHandling() {
    const scrollContainer = document.querySelector('.chart-scroll');
    const chartContainer = document.getElementById('chartContainer');
    if (!scrollContainer || !chartContainer) return;

    function updateScrollVisibility() {
        if (chartContainer.scrollWidth <= scrollContainer.clientWidth) {
            scrollContainer.classList.add('fit-content');
        } else {
            scrollContainer.classList.remove('fit-content');
        }
    }

    window.addEventListener('resize', updateScrollVisibility);
    const observer = new ResizeObserver(updateScrollVisibility);
    observer.observe(chartContainer);
}

/* Wait until DOM ready and Chart.js present */
function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
}

ready(() => {
    if (typeof Chart === "undefined") return;

    // Initialize toggle state from localStorage
    initializeToggleState();
    
    // Initialize all dashboard components
    loadMetrics();
    initializeTimeRangeSlider();
    initializeScrollHandling();

    // Listen for test channel checkbox changes with debouncing
    const cb = document.getElementById("include_test_channels");
    if (cb) {
        let debounceTimer;
        cb.addEventListener("change", (event) => {
            // Save preference to localStorage
            localStorage.setItem('include_test_channels', event.target.checked);
            
            // Debounce the API calls to prevent rapid requests
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                loadMetrics();
                const slider = document.getElementById("timeRangeDays");
                if (slider) {
                    loadPostsPerChannelChart(parseInt(slider.value, 10));
                }
            }, 300);
        });
        
        // Add keyboard support
        cb.addEventListener("keydown", (event) => {
            if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    }
});

function customTooltip(context) {
    let tooltipEl = document.getElementById("chartjs-minimal-tooltip");
    if (!tooltipEl) {
        tooltipEl = document.createElement("div");
        tooltipEl.id = "chartjs-minimal-tooltip";
        tooltipEl.className = "chartjs-tooltip-heatmap";
        document.body.appendChild(tooltipEl);
    }

    const tooltip = context.tooltip;
    if (!tooltip || tooltip.opacity === 0) {
        tooltipEl.style.opacity = 0;
        return;
    }

    let content = "";
    if (tooltip.dataPoints && tooltip.dataPoints.length > 0) {
        const dp = tooltip.dataPoints[0];
        if (context.chart.config.type === "scatter" && dp.raw) {
            const channel = dp.raw.label || "";
            const origSize = dp.raw.x;
            const latency = dp.raw.y;
            const latencyFormatted = latency.toFixed(3);
            const msgId = dp.raw.id !== undefined ? dp.raw.id : "";
            content += `
                <div><strong>Channel:</strong> ${channel}</div>
                <div><strong>Original size:</strong> ${origSize} chars</div>
                <div><strong>Translation time:</strong> ${latencyFormatted} s</div>
                <div><strong>Message ID:</strong> ${msgId}</div>
            `;
        } else {
            let label = dp.label || dp.parsed.x || dp.parsed.y;
            let value = dp.formattedValue || (dp.raw && dp.raw.v) || dp.raw || "";
            label = String(label).replace(/</g, "&lt;").replace(/>/g, "&gt;");
            content += `
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <b>${label}</b> <b>${value}</b>
                </div>
            `;
        }
    }

    const { offsetLeft: posX, offsetTop: posY } = tooltip.chart.canvas;
    tooltipEl.innerHTML = content;
    tooltipEl.style.opacity = 1;

    let left = posX + tooltip.caretX + 14;
    let top = posY + tooltip.caretY + 14;
    tooltipEl.style.left = '0px';
    tooltipEl.style.top = '-9999px';
    tooltipEl.style.display = 'block';
    const tooltipRect = tooltipEl.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    if (left + tooltipRect.width > viewportWidth - 8) {
        left = posX + tooltip.caretX - tooltipRect.width - 14;
        if (left < 0) left = 8;
    }
    tooltipEl.style.left = `${left}px`;
    tooltipEl.style.top = `${top}px`;
}

document.addEventListener("DOMContentLoaded", () => {
    const slider = document.getElementById("timeRangeDays");
    const valueSpan = document.getElementById("timeRangeValue");

    if (!slider || !valueSpan) return;

    valueSpan.textContent = slider.value;

    slider.addEventListener("input", () => {
        valueSpan.textContent = slider.value;
        loadPostsPerChannelChart(parseInt(slider.value, 10));
    });

    loadPostsPerChannelChart(parseInt(slider.value, 10));
});

async function loadPostsPerChannelChart(days) {
    try {
        showLoadingState(true);
        const includeTest = getIncludeTestChannels();
        const res = await fetch(`/api/metrics/summary?days=${days}&include_test_channels=${includeTest ? "1" : "0"}`);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        const json = await res.json();
        if (json.posts_10d_channels) {
            drawPosts10dChannels(json.posts_10d_channels);
        }
        showLoadingState(false);
    } catch (error) {
        console.error('Failed to load posts per channel chart:', error);
        showErrorState(error.message);
        showLoadingState(false);
    }
}

function getIncludeTestChannels() {
    const cb = document.getElementById("include_test_channels");
    return cb ? cb.checked : true;
}

// Initialize toggle state from localStorage
function initializeToggleState() {
    const cb = document.getElementById("include_test_channels");
    if (cb) {
        const savedState = localStorage.getItem('include_test_channels');
        if (savedState !== null) {
            cb.checked = savedState === 'true';
        }
        updateToggleState(cb.checked);
    }
}

// Update toggle visual state and accessibility
function updateToggleState(isChecked) {
    const cb = document.getElementById("include_test_channels");
    const label = cb?.closest('label');
    
    if (cb && label) {
        cb.checked = isChecked;
        cb.setAttribute('aria-checked', isChecked.toString());
        
        // Update visual feedback
        if (isChecked) {
            label.classList.add('bg-blue-50', 'border-blue-200');
            label.classList.remove('bg-gray-50');
        } else {
            label.classList.add('bg-gray-50');
            label.classList.remove('bg-blue-50', 'border-blue-200');
        }
    }
}

// Show/hide loading state
function showLoadingState(isLoading) {
    const loader = document.getElementById("stats-loading");
    const cb = document.getElementById("include_test_channels");
    
    if (loader) {
        loader.classList.toggle('hidden', !isLoading);
    }
    
    if (cb) {
        cb.disabled = isLoading;
        cb.setAttribute('aria-busy', isLoading.toString());
    }
}

// Show error state with user-friendly message
function showErrorState(message) {
    // Remove any existing error messages
    const existingError = document.getElementById('stats-error');
    if (existingError) {
        existingError.remove();
    }
    
    // Create and show new error message
    const errorDiv = document.createElement('div');
    errorDiv.id = 'stats-error';
    errorDiv.className = 'fixed top-4 right-4 bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg shadow-lg z-50 max-w-sm';
    errorDiv.innerHTML = `
        <div class="flex items-start">
            <svg class="w-5 h-5 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"></path>
            </svg>
            <div>
                <strong class="block">Failed to update statistics</strong>
                <span class="text-sm">${message}</span>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-2 text-red-400 hover:text-red-600">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                </svg>
            </button>
        </div>
    `;
    
    document.body.appendChild(errorDiv);
    
    // Auto-remove error after 5 seconds
    setTimeout(() => {
        if (errorDiv && errorDiv.parentElement) {
            errorDiv.remove();
        }
    }, 5000);
}

function drawThroughputLatency({ points }) {
    const ctx = document.getElementById("chartThroughputLatency");
    if (!ctx) return;
    if (throughputLatencyChart) throughputLatencyChart.destroy();
    
    throughputLatencyChart = new Chart(ctx, {
        type: "scatter",
        data: {
            datasets: [
                {
                    label: "Msg size vs. translation time",
                    data: points,
                    pointRadius: 5,
                    backgroundColor: "rgba(59,130,246,0.6)",
                    borderColor: "#3b82f6",
                    parsing: false,
                },
            ],
        },
        options: {
            scales: {
                x: {
                    title: { display: true, text: "Original size (chars)" },
                    beginAtZero: true,
                },
                y: {
                    title: { display: true, text: "Translation time (s)" },
                    beginAtZero: true,
                },
            },
            plugins: {
                tooltip: {
                    enabled: true,
                    callbacks: {
                        title: (items) => {
                            if (!items.length) return '';
                            const item = items[0];
                            const data = item.raw;
                            return `Channel: ${data.label || 'Unknown'}`;
                        },
                        label: (item) => {
                            const data = item.raw;
                            return [
                                `Size: ${data.x} chars`,
                                `Time: ${data.y.toFixed(3)}s`
                            ];
                        }
                    },
                    backgroundColor: 'rgba(255, 255, 255, 0.98)',
                    titleColor: '#374151',
                    bodyColor: '#2563eb',
                    borderColor: 'rgba(226, 232, 240, 0.8)',
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 8,
                    titleFont: {
                        family: "'Roboto', system-ui, -apple-system, sans-serif",
                        size: 13,
                        weight: 500
                    },
                    bodyFont: {
                        family: "'Roboto', system-ui, -apple-system, sans-serif",
                        size: 12,
                        weight: 500
                    }
                },
                legend: { display: false },
            },
        },
    });
}

// Check if the function is called when the page loads
document.addEventListener('DOMContentLoaded', function() {
  loadMetrics();
});

// Also check if we need to refresh metrics periodically
setInterval(() => {
  loadMetrics();
}, 60000); // Refresh every minute
