const age = 33

var socket = io();
let globActive = false;



// Initialize the chart data and configuration
const hr_chart_ctx = document.getElementById('heartRateChart').getContext('2d');
const hr_chart_data = {
    labels: [], // This will hold uptime (as float values)
    datasets: [{
        label: 'Heart Rate (bpm)',
        data: [], // This will hold heart rate values
        borderColor: 'rgba(255, 99, 132, 1)',
        backgroundColor: 'rgba(255, 99, 132, 0.2)',
        borderWidth: 2,
        fill: true,
        pointRadius: 0,
        tension: 0.55 // Add smoothness to the line
    }]
};


const hr_chart_config = {
  type: 'line',
  data: hr_chart_data,
  options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
          x: {
              type: 'linear', // X-axis is now linear (for float uptime values)
              title: {
                  display: false, // No label on the X-axis
              },
              ticks: {
                display: false, // Hide X-axis values
              },
              grid: {
                  display: false // Optionally hide grid lines for cleaner look
              },
              // Adjust range dynamically to show only the last 20 seconds
              min: 0,
              max: 20
          },
          y: {
              beginAtZero: true,
              title: {
                  display: false,
              }
          }
      },
      plugins: {
          legend: {
              display: false // Optionally hide the legend
          }
      }
  }
};

const heartRateChart = new Chart(hr_chart_ctx, hr_chart_config);



socket.on('connect', function() {
    socket.emit('my_event', {data: 'Connected!'});
});


socket.on('test', function(msg) {
  console.log(msg);
});


socket.on('heart_rate_update', function(msg) {
    console.log(msg);

    setHeartRate(age, msg.heart_rate, msg.connected);
    addHeartRate(msg.timestamp, msg.heart_rate);

});

function setHeartRate(age, heartRate, connected) {

  const labels = document.getElementsByClassName("label-heart-rate");
  const pulseElements = document.getElementsByClassName("icon-heart-rate");

  let zone = 1;
  let color = "gray"; // Below Zone 1

  let active = false;
  let animationDuration = 0;

  if (connected && heartRate > 0) {
    const maxHeartRate = 220 - age;
    const percentageOfMax = (heartRate / maxHeartRate) * 100;
    // Determine heart rate zone and font color
    if (percentageOfMax >= 90) {
      zone = 5;
      color = "red"; // Zone 5 (intense)
    } else if (percentageOfMax >= 80) {
      zone = 4;
      color = "orange"; // Zone 4
    } else if (percentageOfMax >= 70) {
      zone = 3;
      color = "yellow"; // Zone 3
    } else if (percentageOfMax >= 60) {
      zone = 2;
      color = "green"; // Zone 2
    }

    active = true;
    animationDuration = (60 / heartRate).toFixed(2);
  } 

  // Update all heart rate labels
  Array.from(labels).forEach(label => {
      label.style.color = color;  // Set font color
      if (active) {
        label.textContent = `${heartRate}`;  // Update label text
      } else {
        label.textContent = "---";
      }
  });

  // Update all heart rate icons
  Array.from(pulseElements).forEach(element => {
    element.style.animationDuration = `${animationDuration}s`;
  });

  // Change Bluetooth symbol if connection status changes
  if (active != globActive) {
    console.log("Bluetooth Status changed!");
    const bluetoothSymbolsConnected = document.getElementsByClassName("bt-connected");
    const bluetoothSymbolsNotConnected = document.getElementsByClassName("bt-not-connected");

    let conOpacity = 0;
    let notConOpacity = 1;
    if (active) {
      conOpacity=1;
      notConOpacity=0;
    }
    // Update all heart rate icons
    Array.from(bluetoothSymbolsConnected).forEach(element => {
      element.style.opacity = conOpacity;
    });

    // Update all heart rate icons
    Array.from(bluetoothSymbolsNotConnected).forEach(element => {
      element.style.opacity = notConOpacity;
    });
    globActive = active;
  }
}

// // Function to add a heart rate value and keep only the last 20 seconds of data
function addHeartRate(timestamp, value) {
    // Add the new heart rate data (uptime and value)
    hr_chart_data.labels.push(timestamp);
    hr_chart_data.datasets[0].data.push(value);

    // Remove data older than 20 seconds
    const currentTime = hr_chart_data.labels[hr_chart_data.labels.length - 1]; // Last timestamp (uptime)
    while (hr_chart_data.labels.length > 0 && currentTime - hr_chart_data.labels[0] > 20) {
      hr_chart_data.labels.shift();  // Remove oldest timestamp (uptime)
      hr_chart_data.datasets[0].data.shift(); // Remove corresponding heart rate
    }

    heartRateChart.options.scales.x.min = hr_chart_data.labels[0];
    heartRateChart.options.scales.x.max = currentTime;
    // Update the chart
    heartRateChart.update('none');
}

function hr_test() {
  console.log("Test clicked");
}