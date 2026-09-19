const { app, BrowserWindow } = require("electron");

app.whenReady().then(() => {
  const win = new BrowserWindow({ width: 1180, height: 780, backgroundColor: "#eef1f2" });
  win.loadURL(process.env.APP_URL || "http://localhost:5173");
});
app.on("window-all-closed", () => app.quit());
