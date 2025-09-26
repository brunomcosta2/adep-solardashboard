let energiaSolInAnimation;

energiaSolInAnimation = lottie.loadAnimation({
  container: document.getElementById('full-animation'),
  renderer: 'svg',
  loop: true,
  autoplay: true,
  path: '/static/Full_Animation_Poste.json' // update if name is different
});

let monthlyChart; 

async function fetchLiveData() {
  try {
    const response = await fetch('/api/live-data');
    const data = await response.json();
	
	function formatNumber(value) {
	  return value
		.toFixed(1)                // 3245.1 → "3245.1"
		.replace('.', ',')         // "3245.1" → "3245,1"
		.replace(/\B(?=(\d{3})+(?!\d))/g, ' '); // "3245,1" → "3 245,1"
	}
	
	function formatPercent(value) {
	  let fixed = value.toFixed(1).replace('.', ','); // 53.0 → "53,0"
	  if (fixed.endsWith(',0')) {
		fixed = fixed.slice(0, -2); // remove ",0"
	  }
	  return fixed + '%';
	}
	
    // Update production and consumption
    document.getElementById('production').innerText = formatNumber(data.production);
    document.getElementById('consumption').innerText = formatNumber(data.consumption);
	
	// Production daily
	document.getElementById('production-energy').innerText = formatNumber(data.total_daily_production);

	// Consumption daily
	document.getElementById('consumption-energy').innerText = formatNumber(data.total_daily_consumption);

	// Surplus daily
	document.getElementById('grid-energy').innerText = formatNumber(data.total_surplus);

	document.getElementById('consumption-percentage').innerText =
    `${formatPercent(data.autoconsumo)} Autoconsumo Diário`;

	document.getElementById('grid-percentage').innerText =
    `${formatPercent(data.autossu)} Autossuficiência Diária`;
	
	const productionMiniBox = document.getElementById('production-percentage');
	
	if (data.production > data.consumption) {
	  // Calculate excedente
	  const excedente = (data.production - data.consumption).toFixed(1).replace('.', ',');
	  productionMiniBox.innerText = `${excedente} kW de excedente`;
	} else if (data.consumption > 0) {
	  // Calculate % of consumption
	  const percentage = ((data.production / data.consumption) * 100).toFixed(1).replace('.', ',');
	  productionMiniBox.innerText = `${percentage}% do Consumo Atual`;
	} else {
	  productionMiniBox.innerText = "Sem Dados";
	}
    // Update grid label and value with correct arrow direction
    const gridValue = (typeof data.grid === 'number' && !isNaN(data.grid)) ? data.grid : 0;
    const gridLabel = document.getElementById('grid-label');
    const gridValueEl = document.getElementById('grid');

    if (gridValue >= 0) {
      gridLabel.innerText = "a consumir da rede";
	  energiaSolInAnimation.setDirection(-1);
      
    } else {
      gridLabel.innerText = "a injetar na rede";
	  energiaSolInAnimation.setDirection(1)
      
    }
    gridValueEl.innerText = formatNumber(Math.abs(gridValue));
	energiaSolInAnimation.goToAndPlay(0, true);
	
	function formatEnergy(value) {
	  let unit = 'kWh';
	  let displayValue = value;

	  if (value >= 1_000_000) {
		displayValue = value / 1_000_000;
		unit = 'GWh';
	  } else if (value >= 1_000) {
		displayValue = value / 1_000;
		unit = 'MWh';
	  }

	  // Format with commas replaced by spaces and 1 decimal
	  const formatted = displayValue
		.toFixed(1)
		.replace('.', ',')
		.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

	  return `${formatted} <span class="unit">${unit}</span>`;
	}

	function formatTonCO2(value) {
	  const rounded = Math.round(value)
        .toString()
        .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');	
	  return `${rounded} <span class="unit">tonCO<sub>2</sub></span>`;
	}
	
	
	 // ✅ Update mini boxes
    const boxMapping = {
	  box1: { key: 'global_total_production', formatter: formatEnergy },
	  box2: { key: 'global_total_emissions', formatter: formatTonCO2 },
	  box3: { key: 'global_total_production', formatter: formatEnergy },
	  box4: { key: 'global_total_emissions', formatter: formatTonCO2 },
	  box5: { key: 'total_self_per', formatter: formatPercent },
	  box6: { key: 'global_total_surplus', formatter: formatEnergy }
	};
	
	Object.entries(boxMapping).forEach(([boxId, { key, formatter }]) => {
      const el = document.querySelector(`#${boxId} .small-box-value`);
      if (el && typeof data[key] === 'number') {
        el.innerHTML = formatter(data[key]);
      }
    });
	
	const monthLabels = [
      'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
      'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'
    ];

    const ctx = document.getElementById('monthlyChart').getContext('2d');

    const chartData = {
      labels: monthLabels,
      datasets: [
        {
          label: "Energia Consumida",
          data: data.monthly_consumption || [],
          backgroundColor: "#224393",
          stack: "stack1",
		  order: 2
        },
        {
          label: "Energia Produzida",
          data: data.monthly_sun || [],
          backgroundColor: "#F79353",
          stack: "stack1",
		  order: 1
        },
        {
          label: "Energia Injetada",
          data: data.monthly_grid || [],
          backgroundColor: "#CE6010",
          stack: "stack1",
		  order: 0
        }
      ]
    };

    const options = {
	  responsive: true,
	  maintainAspectRatio: false, // lets us control height
	  layout: {
		padding: { left: 20 } // move chart a few pixels to the left
	  },
	  plugins: {
		tooltip: {
		  callbacks: {
			label: function (context) {
			  return `${context.dataset.label}: ${context.formattedValue} kWh`;
			}
		  }
		},
		legend: { position: 'top' }
	  },
	  scales: {
		x: {
		  stacked: true,
		  grid: { display: false }, // hide vertical grid lines
		  ticks: { 
		    padding: 5,
			color: '#333333' 
		  } // optional: add some spacing to labels
		},
		y: {
		  stacked: false,
		  grid: { display: false }, // hide horizontal grid lines
		  ticks: { 
			color: '#333333' 
		  },
		  title: { display: true, text: "kWh" },
		  afterDataLimits: (scale) => {
			scale.max = scale.max * 1.3; // increase by 30%
		  }
		}
	  },
	  elements: {
		bar: {
		  borderRadius: (ctx) => {
		    // Apply rounding only to the first dataset (blue bars)
		    if (ctx.datasetIndex === 0) {
			  return { topLeft: 6, topRight: 6, bottomLeft: 0, bottomRight: 0 };
		    }
		    return 0; // other bars (orange) have no rounding
		  },
		  borderSkipped: false,
		  barPercentage: 0.5,  // reduce width of each bar
		  categoryPercentage: 0.6 // reduce total chart width occupied
		}
	  }
	};
	if (monthlyChart) {
	  monthlyChart.destroy();
	}

	// Create the chart
	monthlyChart = new Chart(ctx, {
	  type: 'bar',
	  data: chartData,
	  options: options
	});
	
    hideError();

  } catch (error) {
    console.error('Erro ao buscar dados:', error);
    
  }
}

function showError(message) {
  const errorEl = document.getElementById('error-message');
  errorEl.style.display = 'block';
  errorEl.innerText = message;
}

function hideError() {
  const errorEl = document.getElementById('error-message');
  errorEl.style.display = 'none';
}


lottie.loadAnimation({
  container: document.getElementById('full-animation2'),
  renderer: 'svg',
  loop: true,
  autoplay: true,
  path: '/static/Full_Animation_semPoste.json' // update if name is different
});

function updateDateTime() {
  const now = new Date();
  const date = now.toLocaleDateString('pt-PT');
  const time = now.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });

  document.getElementById('current-date').innerText = date;
  document.getElementById('current-time').innerText = time;
}

setInterval(updateDateTime, 60000);
updateDateTime();

// Get weather from Open-Meteo
async function fetchWeather() {
  try {
    const response = await fetch("https://api.open-meteo.com/v1/forecast?latitude=41.18&longitude=-8.69&current=temperature_2m");
    const data = await response.json();
    const temperature = data.current.temperature_2m;
    document.getElementById('weather').innerText = `${Math.round(temperature)}°C`;
  } catch (error) {
    console.error("Erro ao buscar temperatura:", error);
    document.getElementById('weather').innerText = "--°C";
  }
}

fetchWeather();




setInterval(fetchLiveData, 120000);
fetchLiveData();

const boxes = [
  document.getElementById('grid-box'),
  document.getElementById('production-box'),
  document.getElementById('consumption-box')
];

let currentExpanded = 0;








