// Connect to the Socket.IO server.
// The connection URL has the following format, relative to the current page:
//     http[s]://<domain>:<port>[/<namespace>]
var socket = io();

// Event handler for new connections.
// The callback function is invoked when a connection with the
// server is established.
socket.on('connect', function() {
    socket.emit('my_event', {data: 'I\'m connected!'});
});

// Event handler for server sent data.
// The callback function is invoked whenever the server emits data
// to the client. The data is then displayed in the "Received"
// section of the page.
socket.on('my_response', function(msg) {
    console.log(msg)
});