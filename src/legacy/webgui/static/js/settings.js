// Declare profilesList in the global scope
let profilesList = [];
let isEditing = false;
let customHeartRate = false;
// Fetch profiles when the page loads
document.addEventListener('DOMContentLoaded', () => {
    // Fetch profiles from the backend
    fetch('/api/profiles')
        .then(response => response.json())
        .then(data => {
            // Store the fetched profiles data in the global array
            profilesList = data.profiles;
            
            const profileSelect = document.getElementById('profile-list');
            
            // Populate the <select> with profile names
            profilesList.forEach(profile => {
                // Create an option element for each profile
                const option = document.createElement('option');
                option.value = profile.file_name;  // Set the value attribute
                option.textContent = profile.name;  // Display profile's name
                profileSelect.appendChild(option);
            });

            // Add change event listener to update fields when selection changes
            profileSelect.addEventListener('change', updateProfileFields);


            const button_modify = document.getElementById('button-modify');
            button_modify.addEventListener('click', modifyButtonClick);

            const button_abort = document.getElementById('button-abort');
            button_abort.addEventListener('click', abortButtonClick);

            const button_custom_hr = document.getElementById('button-custom-hr');
            button_custom_hr.addEventListener('click', customHRClick);
            updateProfileFields();
        })
        .catch(error => {
            console.error('Error fetching profiles:', error);
        });
});

// Function to update input fields based on selected profile
function updateProfileFields() {
    const selectedFileName = document.getElementById('profile-list').value;
    
    // Find the selected profile data by matching file_name
    const selectedProfile = profilesList.find(profile => profile.file_name === selectedFileName);
    
    if (selectedProfile) {
        // Update input fields with selected profile data
        document.getElementById('textbox-name').value = selectedProfile.name;
        document.getElementById('textbox-age').value = selectedProfile.age;
        document.getElementById('textbox-hr').value = selectedProfile.max_heart_rate;
        document.getElementById('textbox-pole').value = selectedProfile.pole_length;
    }
}

function modifyButtonClick() {
    // Example functionality: log a message or update fields
    console.log("Update button clicked!");
    if (isEditing) {
        isEditing = false;
        document.getElementById('textbox-name').disabled = true;
        document.getElementById('textbox-age').disabled = true;
        document.getElementById('textbox-hr').disabled = true;
        document.getElementById('textbox-pole').disabled = true;
        document.getElementById('button-custom-hr').disabled = true;
        document.getElementById('button-scan-bt').disabled = true;

    } else {
        isEditing = true;
        document.getElementById('textbox-name').disabled = false;
        document.getElementById('textbox-age').disabled = false;
        document.getElementById('textbox-pole').disabled = false;
        document.getElementById('button-custom-hr').disabled = false;
        document.getElementById('button-scan-bt').disabled = false;
        if (customHeartRate) {
            document.getElementById('textbox-hr').disabled = false;
        }        
    }

}

function abortButtonClick() {
    // Example functionality: log a message or update fields
    console.log("Update button clicked!");
    if (isEditing) {
        isEditing = false;
        document.getElementById('textbox-name').disabled = true;
        document.getElementById('textbox-age').disabled = true;
        document.getElementById('textbox-hr').disabled = true;
        document.getElementById('textbox-pole').disabled = true;
        document.getElementById('button-custom-hr').disabled = true;
        document.getElementById('button-scan-bt').disabled = true;
    }
}

function customHRClick() {
    if (customHeartRate) {
        customHeartRate = false;
        document.getElementById('textbox-hr').disabled = true;    
    } else {
        customHeartRate = true;
        if (isEditing) {
            document.getElementById('textbox-hr').disabled = false; 
        }
    }
}