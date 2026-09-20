const { app, BrowserWindow, desktopCapturer, session } = require("electron");

app.whenReady().then(() => {
  // lets the UI's screen capture work without a picker
  session.defaultSession.setDisplayMediaRequestHandler(
    (req, cb) =>
      desktopCapturer.getSources({ types: ["screen"] }).then((s) => cb({ video: s[0] })),
    { useSystemPicker: false } // Required in Electron 30+: without this the custom handler is ignored
  );
  const win = new BrowserWindow({ width: 1240, height: 800, backgroundColor: "#eef3f1" });
  // Packaged builds default to the hosted production UI; `npm run desktop` still
  // defaults to the local vite dev server. Override either with APP_URL.
  const DEFAULT_URL = app.isPackaged
    ? "http://contextforge-ui-271740378665.s3-website.us-east-1.amazonaws.com"
    : "http://localhost:5173";
  win.loadURL(process.env.APP_URL || DEFAULT_URL);
});
app.on("window-all-closed", () => app.quit());
