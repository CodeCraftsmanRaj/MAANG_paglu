const { app, BrowserWindow, desktopCapturer, session } = require("electron");

app.whenReady().then(() => {
  // lets the UI's screen capture work without a picker
  session.defaultSession.setDisplayMediaRequestHandler((req, cb) =>
    desktopCapturer.getSources({ types: ["screen"] }).then((s) => cb({ video: s[0] })));
  const win = new BrowserWindow({ width: 1240, height: 800, backgroundColor: "#eef3f1" });
  win.loadURL(process.env.APP_URL || "http://localhost:5173");
});
app.on("window-all-closed", () => app.quit());
