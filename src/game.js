const WS = new WebSocket("ws://"+location.host+"/game");
WS.addEventListener("open", ()=>{
    console.log("connected to the server");
});
WS.addEventListener("message", (event)=>{
    console.log(event.data);
});
WS.addEventListener("close", (event)=>{
    console.log("connection closed");
});