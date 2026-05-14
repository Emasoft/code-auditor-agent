// Demo Electron main process entry point.
const { app, BrowserWindow, ipcMain } = require('electron');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: { contextIsolation: true }
  });
  mainWindow.loadFile('index.html');
}

ipcMain.on('save-document', (event, payload) => {
  event.reply('save-document-result', { ok: true });
});

ipcMain.handle('open-file-dialog', async (event, opts) => {
  return { paths: [], canceled: false };
});

ipcMain.once('exit-app', () => {
  app.quit();
});

app.on('ready', () => {
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
