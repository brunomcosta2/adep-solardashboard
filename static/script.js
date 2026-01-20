// Chart initialization
const ctx = document.getElementById('energyChart').getContext('2d');
const energyChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: generateFullDayXAxis(),
    datasets: [
      { label: 'Produção (kW)',         data: [], borderColor: '#FFB300',  fill: false, tension: 0.2 },
      { label: 'Consumo Total (kW)',    data: [], borderColor: '#42A5F5',  fill: false, tension: 0.2 },
      { label: 'Consumo da Rede (kW)',  data: [], borderColor: '#EF5350',  fill: false, tension: 0.2 },
      { label: 'Excedente (kW)',        data: [], borderColor: '#26A69A',  fill: false, tension: 0.2 },
      { label: 'Autoconsumo (kW)',      data: [], borderColor: '#66BB6A',  fill: false, tension: 0.2 }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
	  legend: {
		labels: {
		  color: 'white',
		  usePointStyle: false,
		  pointStyle: 'line',
		  pointStyleWidth: 20,  // length of the line
		  generateLabels: function(chart) {
			  const labels = Chart.defaults.plugins.legend.labels.generateLabels(chart);
			  labels.forEach(label => {
				const dataset = chart.data.datasets[label.datasetIndex];
				label.pointStyle = 'rect';            // square
				label.fillStyle = dataset.borderColor; // fill square with dataset color
				label.strokeStyle = dataset.borderColor; // border also dataset color
				label.lineWidth = 2;                   // optional
			  });
			  return labels;
		  }
		}
	  }
	},
    layout: { padding: 0 },
    scales: {
      x: {
        offset: false,
        ticks: {
          color: 'white',
          autoSkip: false,
          maxRotation: 0,
          minRotation: 0,
          callback: function(value, index) {
            const label = this.getLabelForValue(value);
            return (label.endsWith(':00') && parseInt(label.slice(0, 2)) % 2 === 0)
              ? label
              : '';
          }
        }
      },
      y: {
        ticks: { color: 'white' },
        title: { display: true, text: 'kW', color: 'white' }
      }
    }
  }
});



function generateFullDayXAxis() {
  const labels = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 60; m += 5) {
      const hh = h.toString().padStart(2, '0');
      const mm = m.toString().padStart(2, '0');
      labels.push(`${hh}:${mm}`);
    }
  }
  labels.push("24:00"); // 👈 add end of day marker
  return labels;
}

let firstLoad = true; // track first data fetch
let countdownInterval = null; // track countdown interval
let nextUpdateTime = null; // track when next update should happen
const UPDATE_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes in milliseconds

// Connection status tracking
let lastSuccessfulConnection = null;
let connectionStatus = 'unknown'; // 'connected', 'disconnected', 'unknown'
let failedFetchCount = 0;

// Auto-scroll table variables
let scrollDirection = 1; // 1 = down, -1 = up
let scrollSpeed = 0.5; // pixels per frame (higher = faster) - reduced further for smoother scrolling
let scrollPause = 2000; // pause at top/bottom in milliseconds
let isScrolling = false;
let scrollPaused = false;
let scrollAnimationFrame = null;
let tableWrapper = null;

// Format date/time in Portuguese/European format (DD/MM/YYYY HH:MM:SS)
function formatDateTimePT(date) {
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
}

// Format date in Portuguese/European format (DD/MM/YYYY)
function formatDatePT(date) {
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}/${month}/${year}`;
}

// Format time in HH:MM format
function formatTimePT(date) {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

// Start countdown timer for next update
function startCountdown() {
  // Clear existing interval if any
  if (countdownInterval) {
    clearInterval(countdownInterval);
  }
  
  // Set next update time
  nextUpdateTime = Date.now() + UPDATE_INTERVAL_MS;
  
  // Update countdown immediately
  updateCountdown();
  
  // Update countdown every second
  countdownInterval = setInterval(updateCountdown, 1000);
}

// Update countdown display
function updateCountdown() {
  const countdownElem = document.getElementById('next-update-countdown');
  if (!countdownElem || !nextUpdateTime) return;
  
  const now = Date.now();
  const remaining = Math.max(0, nextUpdateTime - now);
  const seconds = Math.floor(remaining / 1000);
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  
  const formatted = `${minutes}:${String(secs).padStart(2, '0')}`;
  countdownElem.textContent = `Próxima: ${formatted}`;
  
  // Change color based on remaining time
  countdownElem.classList.remove('warning', 'critical');
  if (remaining < 30000) { // Less than 30 seconds
    countdownElem.classList.add('critical');
  } else if (remaining < 60000) { // Less than 1 minute
    countdownElem.classList.add('warning');
  }
  
  // If countdown reached zero, restart it (shouldn't happen, but just in case)
  if (remaining <= 0) {
    startCountdown();
  }
}

// Show updating indicator
function showUpdatingIndicator() {
  const indicator = document.getElementById('update-indicator');
  const countdownElem = document.getElementById('next-update-countdown');
  if (indicator) {
    indicator.textContent = '🔄';
    indicator.classList.add('updating');
  }
  // Show "Atualizando..." text during fetch
  if (countdownElem) {
    countdownElem.textContent = 'Atualizando...';
    countdownElem.classList.remove('warning', 'critical');
  }
}

// Hide updating indicator
function hideUpdatingIndicator() {
  const indicator = document.getElementById('update-indicator');
  if (indicator) {
    indicator.classList.remove('updating');
  }
  // Note: countdown will be restored by startCountdown() after successful fetch
}

async function fetchLiveData() {
  // Pause auto-scroll during data fetch
  stopAutoScroll();
  
  // Show updating indicator
  showUpdatingIndicator();
  try {
    const response = await fetch("/api/live-data");
    
    // Check if fetch was successful (even if response has error)
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();

    if (data.error) {
      console.error("API Error:", data.error);
      updateConnectionStatus(false);
      return;
    }
    
    // Successfully fetched data
    updateConnectionStatus(true);

    // parse numeric values safely
    const production = Number(data.production) || 0;
    const consumption = Number(data.consumption) || 0;
	const gridValNum = production - consumption;
    const totalPlants = Number(data.total_plants) || 0;

    // Update production and consumption displays (only the .value text)
    const prodVal = document.querySelector("#prod .value");
    const consVal = document.querySelector("#cons .value");
    if (prodVal) prodVal.innerText = production.toFixed(2);
    if (consVal) consVal.innerText = consumption.toFixed(2);

    // Compute grid locally and update label + value without replacing structure
    
    const gridLabelElem = document.querySelector("#grid .kpi-label");
    const gridValueElem = document.querySelector("#grid .value");
    if (gridLabelElem && gridValueElem) {
      if (gridValNum >= 0) {
        gridLabelElem.textContent = "🔌 A Injetar na Rede";
        gridValueElem.innerText = gridValNum.toFixed(2);
      } else {
        gridLabelElem.textContent = "🔌 A Consumir da Rede";
        gridValueElem.innerText = Math.abs(gridValNum).toFixed(2);
      }
    }

    // Update monitored plants count
	
	const plantsVal = document.querySelector("#plants .value");
	if (plantsVal) plantsVal.innerText = totalPlants;
	
	// Update last updated timestamp (format in Portuguese/European format)
	const lastUpdatedElem = document.getElementById("last-updated-time");
	if (lastUpdatedElem && data.last_updated) {
	  // Parse the date string (format: YYYY-MM-DD HH:MM:SS) and convert to PT format
	  const dateParts = data.last_updated.split(' ');
	  if (dateParts.length === 2) {
	    const [datePart, timePart] = dateParts;
	    const [year, month, day] = datePart.split('-');
	    lastUpdatedElem.textContent = `${day}/${month}/${year} ${timePart}`;
	  } else {
	    lastUpdatedElem.textContent = data.last_updated;
	  }
	}
	
	// Hide updating indicator and reset countdown
	hideUpdatingIndicator();
	// Reset countdown for next update (5 minutes from now)
	nextUpdateTime = Date.now() + UPDATE_INTERVAL_MS;

	// Alerts
	
	const alertsList = document.getElementById("alertsList");
	alertsList.innerHTML = ""; // clear old alerts

	if (data.alerts && data.alerts.length > 0) {
	  // Add intro sentence
	  const intro = document.createElement("li");
	  intro.textContent = "Alertas e problemas detectados:";
	  intro.style.fontWeight = "bold";  // optional, make it stand out
	  alertsList.appendChild(intro);

	  // Add each alert (installation or account-level)
	  data.alerts.forEach(msg => {
		const li = document.createElement("li");
		li.textContent = msg;
		// Only style warning alerts (⚠️), not critical (🔴) - symbol is enough
		if (msg.includes("⚠️")) {
		  li.style.color = "#ffaa00";
		}
		// No color styling for 🔴 - the symbol is enough
		alertsList.appendChild(li);
	  });
	} else {
	  const li = document.createElement("li");
	  li.textContent = "✅ Todas as instalações estão a funcionar normalmente.";
	  alertsList.appendChild(li);
	}
	
	// Table Code
	const tableBody = document.getElementById("buildingTable");
    tableBody.innerHTML = ""; // clear old rows

    data.statuses.forEach(plant => {
      const row = document.createElement("tr");

      // Grid power: positive = consuming from grid, negative = injecting to grid
      // Show only positive values (consumption from grid), since surplus column shows injection
      const gridConsumption = Math.max(0, plant.grid);
      
      // Format values with conditional styling
      const formatValue = (value, className, showZero = true) => {
        if (value === 0 && !showZero) return '<span class="zero-value">--</span>';
        if (value === 0) return `<span class="zero-value">${value.toFixed(2)}</span>`;
        return `<span class="${className}">${value.toFixed(2)}</span>`;
      };
      
      // Format timestamp if available
      let timestampDisplay = "--";
      if (plant.last_data_time) {
        try {
          // Convert "2026-01-15 14:30" to "15/01/2026 14:30" (PT format)
          const [datePart, timePart] = plant.last_data_time.split(' ');
          if (datePart && timePart) {
            const [year, month, day] = datePart.split('-');
            timestampDisplay = `${day}/${month}/${year} ${timePart}`;
          } else {
            timestampDisplay = plant.last_data_time;
          }
        } catch (e) {
          timestampDisplay = plant.last_data_time;
        }
      }
      
      // If status is critical (🔴) or plant has active alarms, show simplified view
      const isCritical = plant.status_icon === "🔴";
      const hasActiveAlarms = plant.active_alarms && plant.active_alarms.length > 0;
      
      if (isCritical || hasActiveAlarms) {
        // For plants with alarms, show 0.00 for all metrics (not --)
        row.innerHTML = `
          <td><strong>${plant.name}</strong></td>
          <td>${plant.pinstalled ? plant.pinstalled.toFixed(2) : "--"}</td>
          <td><span class="zero-value">0.00</span></td>
          <td><span class="zero-value">0.00</span></td>
          <td><span class="zero-value">0.00</span></td>
          <td><span class="zero-value">--</span></td>
          <td style="font-size: 0.9em; color: #aaa;">${timestampDisplay}</td>
          <td style="font-size: 1.2em;">${plant.status_icon}</td>
        `;
      } else {
        row.innerHTML = `
          <td><strong>${plant.name}</strong></td>
          <td>${plant.pinstalled ? plant.pinstalled.toFixed(2) : "--"}</td>
          <td>${formatValue(plant.production, "prod-value")}</td>
          <td>${formatValue(plant.consumption, "cons-value")}</td>
          <td>${formatValue(gridConsumption, "grid-value", false)}</td>
          <td>${formatValue(plant.surplus, "surplus-value", false)}</td>
          <td style="font-size: 0.9em; color: #aaa;">${timestampDisplay}</td>
          <td style="font-size: 1.2em;">${plant.status_icon}</td>
        `;
      }

      tableBody.appendChild(row);
    });
	
	// Start auto-scroll after table is populated
	// Wait a bit for DOM to update and ensure table wrapper is ready
	setTimeout(() => {
	  if (data.statuses.length > 0) {
	    // Ensure tableWrapper is available
	    if (!tableWrapper) {
	      tableWrapper = document.querySelector('.table-wrapper');
	    }
	    // Reset scroll position to top before starting
	    if (tableWrapper) {
	      tableWrapper.scrollTop = 0;
	      // Force a small delay to ensure scroll position is set
	      setTimeout(() => {
	        startAutoScroll();
	      }, 100);
	    }
	  }
	}, 500); // Increased timeout to ensure DOM is fully updated
	
	// Connection status already updated in try/catch blocks
	
	//Chart Code
	
	if (data.chart && 
	    data.chart.production && 
	    data.chart.grid_consumption &&        // NOVO
	    data.chart.consumption && 
	    data.chart.self_consumption && 
	    data.chart.surplus &&
	    Array.isArray(data.chart.production) &&
	    Array.isArray(data.chart.grid_consumption) &&  // NOVO
	    Array.isArray(data.chart.consumption) &&
	    Array.isArray(data.chart.self_consumption) &&
	    Array.isArray(data.chart.surplus)) {
	  const fullLabels = generateFullDayXAxis();
	  const currentLength = data.chart.x_axis ? data.chart.x_axis.length : 0;

	// Use all available data points (backend handles time filtering)
	  const trimmedProduction      = data.chart.production.slice(0, currentLength);
	  const trimmedGridConsumption = data.chart.grid_consumption.slice(0, currentLength);  // NOVO
	  const trimmedConsumption     = data.chart.consumption.slice(0, currentLength);
	  const trimmedSelfConsumption = data.chart.self_consumption.slice(0, currentLength);
	  const trimmedSurplus         = data.chart.surplus.slice(0, currentLength);

	  // Fill missing future points with null
	  const paddedProduction      = [...trimmedProduction];
	  const paddedGridConsumption = [...trimmedGridConsumption];  // NOVO
	  const paddedConsumption     = [...trimmedConsumption];
	  const paddedSelfConsumption = [...trimmedSelfConsumption];
	  const paddedSurplus         = [...trimmedSurplus];

	  while (paddedProduction.length < fullLabels.length) {
		paddedProduction.push(null);
		paddedGridConsumption.push(null);  // NOVO
		paddedConsumption.push(null);
		paddedSelfConsumption.push(null);
		paddedSurplus.push(null);
	  }

	  energyChart.data.labels = fullLabels;
	  energyChart.data.datasets[0].data = paddedProduction;       // Produção
	  energyChart.data.datasets[1].data = paddedConsumption;      // Consumo Total
	  energyChart.data.datasets[2].data = paddedGridConsumption;  // Consumo da Rede
	  energyChart.data.datasets[3].data = paddedSurplus;          // Excedente
	  energyChart.data.datasets[4].data = paddedSelfConsumption;  // Autoconsumo
	  energyChart.update();
	}
	
  if (firstLoad) {
      document.getElementById("loading-overlay")?.classList.add("hidden");
      firstLoad = false;
    }	
  } catch (error) {
    console.error("Erro ao buscar dados:", error);
    // Update connection status to disconnected
    updateConnectionStatus(false);
    // Hide updating indicator even on error
    hideUpdatingIndicator();
    // Still reset countdown so it continues (will retry in 5 minutes)
    nextUpdateTime = Date.now() + UPDATE_INTERVAL_MS;
  }
}

// Update connection status indicator (integrated in update widget)
function updateConnectionStatus(success) {
  const updateWidget = document.getElementById('update-widget');
  const connectionIndicator = document.getElementById('connection-indicator');
  const connectionText = document.getElementById('connection-text');
  
  if (!updateWidget || !connectionIndicator || !connectionText) {
    return;
  }
  
  if (success) {
    // Successful connection to Fusion Solar API
    connectionStatus = 'connected';
    failedFetchCount = 0;
    lastSuccessfulConnection = new Date();
    
    // Update UI
    updateWidget.classList.remove('disconnected');
    updateWidget.classList.add('connected');
    connectionIndicator.textContent = '🟢';
    connectionText.textContent = 'Online';
  } else {
    // Failed connection (API error, network error, etc.)
    connectionStatus = 'disconnected';
    failedFetchCount++;
    
    // Update UI
    updateWidget.classList.remove('connected');
    updateWidget.classList.add('disconnected');
    connectionIndicator.textContent = '🔴';
    connectionText.textContent = 'Offline';
  }
}

// Run once on load
fetchLiveData();

// Start countdown timer
startCountdown();

// Refresh every 5 minutes
setInterval(fetchLiveData, UPDATE_INTERVAL_MS);



// Weather fetch (Open-Meteo)
async function fetchWeather() {
  try {
    const response = await fetch("https://api.open-meteo.com/v1/forecast?latitude=41.1579&longitude=-8.6291&current_weather=true");
    const data = await response.json();

    const temperature = data.current_weather.temperature;
    const weatherCode = data.current_weather.weathercode;
	
    // WMO Weather Interpretation Codes (Open-Meteo uses WMO codes 0-99)
    // Complete mapping for all possible weather codes
    const weatherMap = {
        // Clear sky
        0: "/static/sunny.svg",
        // Mainly clear
        1: "/static/partly_sunny.svg",
        // Partly cloudy
        2: "/static/partly_cloudy.svg",
        // Overcast
        3: "/static/cloudy.svg",
        // Fog and depositing rime fog
        45: "/static/fog.svg",
        48: "/static/fog.svg",
        // Drizzle: Light, moderate, dense intensity
        51: "/static/drizzle.svg",
        53: "/static/drizzle.svg",
        55: "/static/drizzle.svg",
        // Freezing Drizzle: Light, moderate, dense intensity
        56: "/static/drizzle.svg",
        57: "/static/drizzle.svg",
        // Rain: Slight, moderate, heavy intensity
        61: "/static/rain.svg",
        63: "/static/rain.svg",
        65: "/static/rain.svg",
        // Freezing Rain: Light, moderate, heavy intensity
        66: "/static/rain.svg",
        67: "/static/rain.svg",
        // Snow fall: Slight, moderate, heavy intensity
        71: "/static/snow.svg",
        73: "/static/snow.svg",
        75: "/static/snow.svg",
        // Snow grains
        77: "/static/snow.svg",
        // Rain showers: Slight, moderate, violent
        80: "/static/rain.svg",
        81: "/static/rain.svg",
        82: "/static/rain.svg",
        // Snow showers: Slight, moderate, heavy
        85: "/static/snow.svg",
        86: "/static/snow.svg",
        // Thunderstorm: Slight, moderate, with hail
        95: "/static/thunderstorm.svg",
        96: "/static/thunderstorm.svg",
        99: "/static/thunderstorm.svg"
    };

    const iconPath = weatherMap[weatherCode];

    // Update DOM
    document.getElementById('weather').innerText = `${Math.round(temperature)}°C`;
    
    // If no mapping found, use a fallback emoji instead of missing SVG
    if (!iconPath) {
      console.warn(`Unknown weather code: ${weatherCode}, using fallback emoji`);
      document.getElementById('weather-icon').innerHTML = "🌤️";
    } else {
      document.getElementById('weather-icon').innerHTML = `<img src="${iconPath}" width="60" height="60" alt="Weather Icon">`;
    }
    document.getElementById('humidity').innerText = ""; // Open-Meteo current_weather does not provide humidity

  } catch (error) {
    console.error("Erro ao buscar clima:", error);
    document.getElementById('weather').innerText = "--°C";
    document.getElementById('weather-icon').innerText = "❓";
    document.getElementById('humidity').innerText = "💧 --%";
  }
}

// Auto-scroll table function
function autoScrollTable() {
  // Get table wrapper if not available
  if (!tableWrapper) {
    tableWrapper = document.querySelector('.table-wrapper');
  }
  
  // Stop if no wrapper or scrolling is disabled
  if (!tableWrapper) {
    return;
  }
  
  if (!isScrolling) {
    return;
  }
  
  // If paused (at top/bottom), don't scroll
  if (scrollPaused) {
    return;
  }
  
  const currentScroll = tableWrapper.scrollTop;
  const maxScroll = tableWrapper.scrollHeight - tableWrapper.clientHeight;
  
  // If table content doesn't need scrolling, don't scroll
  if (maxScroll <= 0) {
    return;
  }
  
  // Check if we've reached top or bottom
  // Use a small threshold to detect when we're at the edges
  const threshold = 2;
  const isAtTop = currentScroll <= threshold;
  const isAtBottom = currentScroll >= (maxScroll - threshold);
  
  if (isAtTop || isAtBottom) {
    if (!scrollPaused) {
      scrollPaused = true;
      const wasAtBottom = isAtBottom; // Store which edge we hit
      
      // Ensure we're exactly at the edge
      if (isAtTop) {
        tableWrapper.scrollTop = 0;
      } else if (isAtBottom) {
        tableWrapper.scrollTop = maxScroll;
      }
      
      // Stop current animation
      if (scrollAnimationFrame) {
        cancelAnimationFrame(scrollAnimationFrame);
        scrollAnimationFrame = null;
      }
      
      setTimeout(() => {
        // Reverse direction
        scrollDirection *= -1;
        scrollPaused = false;
        
        // Force immediate scroll to get out of the edge detection
        // Move slightly away from the edge based on new direction
        const currentScrollAfterPause = tableWrapper.scrollTop;
        const maxScrollAfterPause = tableWrapper.scrollHeight - tableWrapper.clientHeight;
        
        if (wasAtBottom && scrollDirection < 0) {
          // Was at bottom, now going up - move up from bottom
          tableWrapper.scrollTop = Math.max(0, maxScrollAfterPause - 10);
        } else if (!wasAtBottom && scrollDirection > 0) {
          // Was at top, now going down - move down from top
          tableWrapper.scrollTop = Math.min(maxScrollAfterPause, 10);
        }
        
        // Continue scrolling in new direction
        if (isScrolling) {
          scrollAnimationFrame = requestAnimationFrame(autoScrollTable);
        }
      }, scrollPause);
    }
    return;
  }
  
  // Continuous scroll
  const oldScrollTop = tableWrapper.scrollTop;
  const newScrollTop = oldScrollTop + (scrollSpeed * scrollDirection);
  
  // Clamp new scroll position to valid range
  const clampedScrollTop = Math.max(0, Math.min(maxScroll, newScrollTop));
  
  // Only update if position would actually change
  if (Math.abs(clampedScrollTop - oldScrollTop) >= 0.1) {
    tableWrapper.scrollTop = clampedScrollTop;
  } else {
    // We've reached a limit - the edge detection above should catch this
    // but if it doesn't, schedule next frame to let edge detection handle it
    // This prevents infinite loops while ensuring scroll continues
    scrollAnimationFrame = requestAnimationFrame(autoScrollTable);
    return;
  }
  
  // Schedule next frame - must always be called to continue animation
  scrollAnimationFrame = requestAnimationFrame(autoScrollTable);
}

// Stop auto-scroll
function stopAutoScroll() {
  isScrolling = false;
  if (scrollAnimationFrame) {
    cancelAnimationFrame(scrollAnimationFrame);
    scrollAnimationFrame = null;
  }
}

// Start auto-scroll
function startAutoScroll() {
  // Get table wrapper if not available
  if (!tableWrapper) {
    tableWrapper = document.querySelector('.table-wrapper');
  }
  
  if (!tableWrapper) {
    return;
  }
  
  // Stop any existing scroll animation first
  if (scrollAnimationFrame) {
    cancelAnimationFrame(scrollAnimationFrame);
    scrollAnimationFrame = null;
  }
  
  // Check if scrolling is needed
  const maxScroll = tableWrapper.scrollHeight - tableWrapper.clientHeight;
  
  if (maxScroll <= 0) {
    // Table doesn't need scrolling
    isScrolling = false;
    return;
  }
  
  // Always reset and start scrolling
  isScrolling = true;
  scrollPaused = false; // Reset paused state when starting
  scrollDirection = 1; // Always start scrolling down
  
  // Start the animation loop immediately
  if (!scrollAnimationFrame) {
    scrollAnimationFrame = requestAnimationFrame(autoScrollTable);
  }
}

// Clock + Date updater (Portuguese/European format)
function updateClock() {
  const now = new Date();
  const time = formatTimePT(now);
  const date = formatDatePT(now);
  document.getElementById('time').innerText = time;
  document.getElementById('date').innerText = date;
}

// Setup table auto-scroll pause on hover
document.addEventListener('DOMContentLoaded', () => {
  tableWrapper = document.querySelector('.table-wrapper');
  if (tableWrapper) {
    // Pause scroll on hover
    tableWrapper.addEventListener('mouseenter', () => {
      stopAutoScroll();
    });
    
    // Resume scroll when mouse leaves
    tableWrapper.addEventListener('mouseleave', () => {
      startAutoScroll();
    });
    
    // Also pause when user manually scrolls
    let userScrolling = false;
    let scrollTimeout = null;
    tableWrapper.addEventListener('wheel', (e) => {
      userScrolling = true;
      stopAutoScroll();
      
      // Resume after user stops scrolling for 3 seconds
      clearTimeout(scrollTimeout);
      scrollTimeout = setTimeout(() => {
        userScrolling = false;
        const maxScroll = tableWrapper.scrollHeight - tableWrapper.clientHeight;
        if (maxScroll > 0) {
          startAutoScroll();
        }
      }, 3000);
    }, { passive: true });
    
    // Resume after touch scroll on mobile
    tableWrapper.addEventListener('touchmove', () => {
      userScrolling = true;
      stopAutoScroll();
    }, { passive: true });
    
    tableWrapper.addEventListener('touchend', () => {
      scrollTimeout = setTimeout(() => {
        userScrolling = false;
        const maxScroll = tableWrapper.scrollHeight - tableWrapper.clientHeight;
        if (maxScroll > 0) {
          startAutoScroll();
        }
      }, 3000);
    });
  }
});

fetchWeather();
setInterval(fetchWeather, 10 * 60 * 1000); // refresh every 10 min
updateClock();
setInterval(updateClock, 30 * 1000); // update clock every minute








