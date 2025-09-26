// Chart initialization
const ctx = document.getElementById('energyChart').getContext('2d');
const energyChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: generateFullDayXAxis(),
    datasets: [
      { label: 'Produção', data: [], borderColor: 'orange', fill: false, tension: 0.2 },
      { label: 'Consumo', data: [], borderColor: '#3898FE', fill: false, tension: 0.2 },
      { label: 'Autoconsumo', data: [], borderColor: 'red', fill: false, tension: 0.2 },
      { label: 'Excedente', data: [], borderColor: '#18CF87', fill: false, tension: 0.2 }
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

async function fetchLiveData() {
  try {
    const response = await fetch("/api/live-data");
    const data = await response.json();

    if (data.error) {
      console.error("API Error:", data.error);
      return;
    }

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

	// Alerts
	
	const alertsList = document.getElementById("alertsList");
	alertsList.innerHTML = ""; // clear old alerts

	if (data.alerts && data.alerts.length > 0) {
	  // Add intro sentence
	  const intro = document.createElement("li");
	  intro.textContent = "As seguintes instalações estão com problemas:";
	  intro.style.fontWeight = "bold";  // optional, make it stand out
	  alertsList.appendChild(intro);

	  // Add each problematic installation
	  data.alerts.forEach(msg => {
		const li = document.createElement("li");
		li.textContent = msg;
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

      row.innerHTML = `
        <td>${plant.name}</td>
        <td>${plant.pinstalled || "--"}</td>
        <td>${plant.production.toFixed(2)}</td>
        <td>${plant.consumption.toFixed(2)}</td>
		<td>${plant.grid.toFixed(2)}</td>
        <td>${plant.surplus.toFixed(2)}</td>
        <td>${plant.status_icon}</td>
      `;

      tableBody.appendChild(row);
    });
	
	//Chart Code
	
	if (data.chart) {
	  const fullLabels = generateFullDayXAxis();
	  const currentLength = data.chart.x_axis.length;
	
	// --- Drop the very last available data point (if at least 2 points exist)
	  const safeLength = currentLength > 2 ? currentLength - 2 : currentLength;

	  const trimmedProduction = data.chart.production.slice(0, safeLength);
	  const trimmedConsumption = data.chart.consumption.slice(0, safeLength);
	  const trimmedSelfConsumption = data.chart.self_consumption.slice(0, safeLength);
	  const trimmedSurplus = data.chart.surplus.slice(0, safeLength);
	
	  // Fill missing future points with null
	  const paddedProduction = [...trimmedProduction];
	  const paddedConsumption = [...trimmedConsumption];
	  const paddedSelfConsumption = [...trimmedSelfConsumption];
	  const paddedSurplus = [...trimmedSurplus];

	  while (paddedProduction.length < fullLabels.length) {
		paddedProduction.push(null);
		paddedConsumption.push(null);
		paddedSelfConsumption.push(null);
		paddedSurplus.push(null);
	  }

	  energyChart.data.labels = fullLabels;
	  energyChart.data.datasets[0].data = paddedProduction;
	  energyChart.data.datasets[1].data = paddedConsumption;
	  energyChart.data.datasets[2].data = paddedSelfConsumption;
	  energyChart.data.datasets[3].data = paddedSurplus;
	  energyChart.update();
	}
	
  if (firstLoad) {
      document.getElementById("loading-overlay")?.classList.add("hidden");
      firstLoad = false;
    }	
  } catch (error) {
    console.error("Erro ao buscar dados:", error);
  }
}

// Run once on load
fetchLiveData();

// Refresh every 5 minutes
setInterval(fetchLiveData, 5 * 60 * 1000);



// Weather fetch (Open-Meteo)
async function fetchWeather() {
  try {
    const response = await fetch("https://api.open-meteo.com/v1/forecast?latitude=41.1579&longitude=-8.6291&current_weather=true");
    const data = await response.json();

    const temperature = data.current_weather.temperature;
    const weatherCode = data.current_weather.weathercode;
	

    const weatherMap = {
        0: "/static/sunny.svg",
        1: "/static/partly_sunny.svg",
        2: "/static/partly_cloudy.svg",
        3: "/static/cloudy.svg",
        45: "/static/fog.svg",
        48: "/static/fog.svg",
        51: "/static/drizzle.svg",
        61: "/static/rain.svg",
        71: "/static/snow.svg",
        95: "/static/thunderstorm.svg"
    };

    const iconPath = weatherMap[weatherCode] || "/static/unknown.svg";

    // Update DOM
    document.getElementById('weather').innerText = `${Math.round(temperature)}°C`;
    document.getElementById('weather-icon').innerHTML = `<img src="${iconPath}" width="60" height="60" alt="Weather Icon">`;
    document.getElementById('humidity').innerText = ""; // Open-Meteo current_weather does not provide humidity

  } catch (error) {
    console.error("Erro ao buscar clima:", error);
    document.getElementById('weather').innerText = "--°C";
    document.getElementById('weather-icon').innerText = "❓";
    document.getElementById('humidity').innerText = "💧 --%";
  }
}

// Clock + Date updater
function updateClock() {
  const now = new Date();
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const date = now.toLocaleDateString();
  document.getElementById('time').innerText = time;
  document.getElementById('date').innerText = date;
}

fetchWeather();
setInterval(fetchWeather, 10 * 60 * 1000); // refresh every 10 min
updateClock();
setInterval(updateClock, 30 * 1000); // update clock every minute








