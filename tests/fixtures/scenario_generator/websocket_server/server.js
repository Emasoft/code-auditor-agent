// fixture for websocket_server — exercises three handler-registration
// shapes the discoverer must handle:
//   1. wss.on('connection', socket => { socket.on('message', ...) })
//      → WS_MESSAGE_HANDLER (the inner 'message' listener)
//   2. socket.on('close', handler)
//      → WS_MESSAGE_HANDLER (event listener on a socket)
//   3. io.on('connection', socket => { socket.on('chat', ...) })
//      → WS_MESSAGE_HANDLER (socket.io named event)
const { WebSocketServer } = require('ws');
const { Server } = require('socket.io');

// Plain `ws` server.
const wss = new WebSocketServer({ port: 8080 });

wss.on('connection', function onConnection(socket) {
  // Incoming text/binary frame from a connected client.
  socket.on('message', function onMessage(data) {
    socket.send(JSON.stringify({ echo: data.toString() }));
  });

  // Connection terminated by either side.
  socket.on('close', function onClose(code, reason) {
    console.log('closed', code, reason);
  });
});

// Socket.io server — distinct from plain ws but uses the same .on() API.
const io = new Server(3001);

io.on('connection', function onIoConnection(socket) {
  // Application-defined event ('chat') from a connected client.
  socket.on('chat', function onChat(payload) {
    socket.broadcast.emit('chat', payload);
  });
});
