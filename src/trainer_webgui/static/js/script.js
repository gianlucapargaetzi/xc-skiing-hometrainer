// script.js
const resizer = document.getElementById('resizer');
const leftPanel = document.getElementById('modePanel');
const rightPanel = document.getElementById('analyticsPanel');
const taskBar = document.getElementById('taskBar')


let isResizing = false;

const buttons = document.querySelectorAll(".round-button--toggle");

// for (let button of buttons) {
// 	button.addEventListener("click", function () {
// 		button.classList.toggle("is-active");
// 	});
// }



resizer.addEventListener('mousedown', (event) => {
    isResizing = true;
});

document.addEventListener('mousemove', (event) => {
    if (!isResizing) return;
    const newWidth = event.clientX - leftPanel.getBoundingClientRect().left;


    if (newWidth > leftPanel.style.minWidth && newWidth < window.innerWidth - 300) { // Set min/max limits
        leftPanel.style.width = newWidth + 'px';
    }
    
});

document.addEventListener('mouseup', () => {
    if (isResizing)  {
        L.map('map').invalidateSize(true);
        isResizing = false;
    }
});

document.addEventListener('DOMContentLoaded', function () {
  // Select the checkbox element
  const checkbox = document.getElementById('control-mode-toggle');
  const view1 = document.getElementById('mode-view-gps');
  const view2 = document.getElementById('mode-view-manual');

  // Listen for changes on the checkbox
  checkbox.addEventListener('change', function () {
      // Get the current state of the checkbox
      const checkboxState = checkbox.checked;

      // Function to toggle views based on checkbox state
      function toggleViews() {
          if (checkbox.checked) {
              view1.style.display='none';
              view2.style.display='flex';
          } else {
              view1.style.display='flex';
              view2.style.display='none';
          }
      }

      toggleViews();
      // Send an AJAX POST request to the Flask backend
      fetch('/update-checkbox', {
          method: 'POST',
          headers: {
              'Content-Type': 'application/json'
          },
          body: JSON.stringify({ checkbox_state: checkboxState })
      })
      .then(response => response.json())
      .then(data => {
          console.log("Checkbox state updated on server:", data);
      })
      .catch(error => {
          console.error('Error updating checkbox state:', error);
      });
  });
});


function openSettingsPage() {
    window.open('/settings', '_blank'); // Open Flask route /settings in a new tab
  }


window.onbeforeunload = function(event) {

    fetch('/release-session', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
    })
    
    event.preventDefault();
    event.returnValue = ''; // Default message shown
};

