// Keep potentially large verifier feedback out of the Windows command line.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const request = JSON.parse(readFileSync(process.argv[2], 'utf8'));
process.argv = [process.execPath, request.entry, ...request.argv];
await import(pathToFileURL(request.entry).href);
