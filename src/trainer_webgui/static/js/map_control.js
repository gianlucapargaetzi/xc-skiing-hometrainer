const ctxElevation = document.getElementById('elevationChart').getContext('2d');
let elevationChart = null;
let currentPositionMarker = null;
let elevationHighlightPoint = null;

let map = L.map('map').setView([0, 0], 2);
let baseMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
});

baseMap.addTo(map);

// Upload GPX File and Display Map & Chart
function uploadGpxFile() {
    const fileInput = document.getElementById('gps-upload');

    const map_view = document.getElementById('map');
    const elevation_gain_view = document.getElementById('elevation-plot');


    const file = fileInput.files[0];

    // if (!file) {
    //     alert('Please select a GPX file first.');
    //     return;
    // }

    const formData = new FormData();
    formData.append('gpxFile', file);

    // Send the file to the server using Fetch API
    fetch('/set-gpx', {
        method: 'POST',
        body: formData,
    })
    .then(response => {
        if (response.ok) {
            map_view.style.display= 'block';
            elevation_gain_view.style.display = 'block';
            return response.json();  // Parse the JSON response if successful

        } else {
            // Handle other response statuses (400, 500, etc.
            map_view.style.display= 'none';
            elevation_gain_view.style.display = 'none';
            console.error(`Server responded with status code: ${response.status}`);
            throw new Error(`Failed to upload file. Status code: ${response.status}`);
        }
    })
    .then(data => {
        if (data.success) {
            const gpxData = data.gpx;  // List of coordinates from GPX file
            const latLngs = gpxData.map(coord => [coord.lat, coord.lon]);
            // map_view.gain_view.style.display= 'block';
            // elevation_gain_view.style.display = 'block';
        
            // Display the GPX track on the Leaflet map
            map.eachLayer(layer => { 
                if (layer !== baseMap) {
                    map.removeLayer(layer);
                } 
            });



            // L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            //     maxZoom: 19,
            //     attribution: '© OpenStreetMap contributors'
            // }).addTo(map);
            
            
            const polyline = L.polyline(latLngs, { color: 'blue' }).addTo(map);

            // Get the current position data from the server response
            const currentPosition = data.position;  // { lat: <value>, lon: <value>, elevation: <value>, distance: <value> }
            // Add a marker to the map at the current position

            updatePosition(currentPosition);


            // if (currentPositionMarker) {
            //     map.removeLayer(currentPositionMarker);
            // }
            // currentPositionMarker = L.marker([currentPosition.lat, currentPosition.lon]).addTo(map);

            map.invalidateSize(false);
            map.fitBounds(polyline.getBounds());

            // Extract elevation data for the chart
            const elevationData = gpxData.map(coord => coord.elevation || 0);  // Assume elevation is in 'coord.elevation'
            const distanceData = gpxData.map(coord => parseFloat(coord.distance).toFixed(1) || 0);  // Simple distance measure (index as x-axis)

            updateElevationChart(distanceData, elevationData);

            // Highlight the current position on the elevation chart
            //highlightElevationPoint(currentPosition.distance, currentPosition.elevation);
        }
    })
    .catch(error => {
        console.error('Error:', error)
    });

    setTimeout(() => {
        map.invalidateSize(true);
    }, 250);
}

function updatePosition() {
    fetch('/current-position')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                setMapPosition(data.position)
            }
        });
}

function setMapPosition(position) {
    if (currentPositionMarker) {
        map.removeLayer(currentPositionMarker);
    }
    currentPositionMarker = L.marker([position.lat, position.lon]).addTo(map);
}

// Function to update the elevation chart with new data
function updateElevationChart(labels, data) {
    if (!elevationChart) {
        elevationChart = new Chart(ctxElevation, {
            type: 'line',
            data: {
                labels: labels,  // X-axis labels (e.g., distance or time)
                datasets: [{
                    label: 'Elevation (m)',
                    data: data,  // Y-axis data (e.g., elevation values)
                    borderColor: '#007aff',
                    backgroundColor: 'rgba(0, 122, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Distance (km)'
                        }
                    },
                    y: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Elevation (m)'
                        }
                    }
                }
            }
        });
    } else {
        elevationChart.data.labels = labels;
        elevationChart.data.datasets[0].data = data;
        elevationChart.update();
    }
}

function highlightElevationPoint(distance, elevation) {
    const pointIndex = elevationChart.data.labels.indexOf(distance.toFixed(1));  // Find the index of the distance point in chart

    if (pointIndex !== -1) {
        // Remove previous highlight if it exists
        if (elevationHighlightPoint) {
            elevationHighlightPoint.remove();
        }

        // Create a vertical line to highlight the point on the elevation chart
        elevationHighlightPoint = new Chart.AnnotationPlugin({
            type: 'line',
            xMin: distance,
            xMax: distance,
            borderColor: 'red',
            borderWidth: 2,
            label: {
                content: `Current Position: ${elevation}m`,
                enabled: true,
                position: 'top'
            }
        });
        elevationChart.options.plugins = {
            annotation: {
                annotations: [elevationHighlightPoint]
            }
        };

        elevationChart.update();
    }
}


// Call updateChart every 2 seconds to refresh the chart

// setInterval(updatePosition, 1000);
// Initial load of the chart data
window.onload = uploadGpxFile;
  