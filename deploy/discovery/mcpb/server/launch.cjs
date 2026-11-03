'use strict';
// Dependency-free connector: no shell, installation, downloads or privilege elevation.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

function fail(message) {
  console.error(`Omneum connector: ${message}`);
  process.exit(1);
}
if (!['darwin', 'linux'].includes(process.platform)) fail('local serving requires macOS or Ubuntu.');
if (process.getuid && process.getuid() === 0) fail('run as the normal login account that installed Omneum.');
const args = process.argv.slice(2);
if (args.length !== 1 || !path.isAbsolute(args[0]) || path.basename(args[0]) !== 'omneum-server') {
  fail('select the absolute installed omneum-server executable after pip install omneum and omneum install.');
}
try {
  if (!fs.statSync(args[0]).isFile()) fail('the selected executable is not a file.');
  fs.accessSync(args[0], fs.constants.X_OK);
} catch {
  fail('omneum-server is missing or not executable; complete pip install omneum and omneum install first.');
}
const child = spawn(args[0], [], { shell: false, stdio: 'inherit' });
child.on('error', () => fail('could not start the installed server; check its Python environment and daemon installation.'));
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => child.kill(signal));
child.on('exit', (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code === null ? 1 : code);
});
