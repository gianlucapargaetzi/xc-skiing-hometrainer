let started = false;
let positionUpdateInterval = null;
function startStop() {
    const button = document.getElementById('start-stop-button');

    if (started) {
        if (positionUpdateInterval != null) {
            clearInterval(positionUpdateInterval)
            positionUpdateInterval = null;
        }
        started=false;
        button.value = "Start";
    } else {
        if (positionUpdateInterval != null) {
            clearInterval(positionUpdateInterval)

        }
        positionUpdateInterval = setInterval(updatePosition, 1000);

        started=true;
        button.value = "Stop";
    }
}

